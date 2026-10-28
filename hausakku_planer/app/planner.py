#!/usr/bin/env python3
"""Hausakku planner: deterministic calculation and verified HA schedule publication.
Default is read/compute only; --publish writes own helpers, NEVER hardware.
"""
import argparse,asyncio,fcntl,json,math,sys,time,copy,hashlib
from dataclasses import replace
from datetime import datetime,timedelta
from pathlib import Path
from collector import collect
from forecast import TZ
from planner_data import prepare
from optimizer import Interval,Params,optimize,schedules,_replay
from operating_policy import choose_operation
from forecast_learning import apply_learning,public_model_summary,refresh_learning,snapshot_observations
from forecast_audit import archive_forecast,score_forecasts,audit_summary
from publisher import publish,publish_ev_window,validate_schedule_pair,expire
import ev_charging
from ha_client import connection
import paths,settings
import spot_prices
from openmeteo import apply_radiation,archive_radiation,load_history,refresh_history
from multiday import archive_weather,build_tail,scenario_rows,continuation_curve,archive_prices,read_prices,archive_issue,score_issues,seed_price_archive
BASE=paths.DATA

def load_config(base=None):
    """<base>/config.json overrides everything (developer escape hatch); otherwise settings + neutral defaults."""
    path=(base or BASE)/'config.json'
    return json.loads(path.read_text()) if path.exists() else settings.current().planner_config()
DAYS=('monday','tuesday','wednesday','thursday','friday','saturday','sunday')

def schedule_payloads(week):
    charge={d:[] for d in DAYS};serve={d:[] for d in DAYS}
    for short,day in zip(('mon','tue','wed','thu','fri','sat','sun'),DAYS):
        for x in week[short]:
            target=charge if x['mode']=='charge' else serve if x['mode']=='serve' else None
            if target is not None:target[day].append({'from':x['start'],'to':x['end'],'data':x['data']})
    validate_schedule_pair(charge,serve)
    return charge,serve


def tail_end_value(config):
    """Lower-bound value of energy left after the tail: floor price times discharge efficiency."""
    floor=config.get('tail_price_floor_eur_kwh')
    if not config.get('tail_end_value_from_floor') or floor is None:return 0.
    return max(0.,float(floor))*float(config['discharge_efficiency'])


IDLE_CHARGE_KWH=.02

def idle_charge_as_hold(plan,rows,params):
    """Publish charge intervals without planned charger energy as hold.
    In the model both are identical once the grid-charge ceiling is reached, but in HA an
    open charge window would keep charging at evening prices if the real SOC lags the plan."""
    # Slivers below 20 Wh per interval (e.g. the partial interval at 'now') are no charge plan:
    # they would keep the target SOC at the ceiling and trigger pointless republication.
    modes=['hold' if m=='charge' and f['charger_ac_kwh']<IDLE_CHARGE_KWH else m for m,f in zip(plan['modes'],plan['intervals'])]
    if modes==plan['modes']:return plan
    replay=_replay(rows,modes,params)
    if abs(replay['cost_eur']-plan['cost_eur'])>.02 or abs(replay['terminal_kwh']-plan['terminal_kwh'])>.1:
        raise ValueError('Idle charge relabelling changed physical flows')
    return {**plan,'modes':replay['modes'],'intervals':replay['intervals']}


def compute_plan(snapshot,config,learning_artifact=None,dataset=None,price_history=None,price_evidence=None,radiation_history=None):
    if config.get('mode') not in ('shadow','recommendation_only'):raise ValueError('Planner only writes recommendations, never hardware')
    if not config.get('pv_dc_coupled',False):raise ValueError('Only provisional DC-coupled PV model supported')
    data=prepare(snapshot,config)
    baseline={'intervals':[{k:(v.isoformat() if isinstance(v,datetime) else v) for k,v in row.items()} for row in data['intervals']],
              'pv_totals_corrected_kwh':dict(data['pv_totals_corrected_kwh'])}
    data,forecast_model=apply_learning(data,snapshot,learning_artifact)
    if not forecast_model.get('applied',{}).get('load') and config.get('load_estimator')=='weighted_mean':
        # Keep the learning baseline id ('median28') intact for the audit; report the operational estimator separately.
        forecast_model['operational_load']=f"gewichtetes Mittel, Halbwertszeit {float(config.get('load_half_life_days',7)):g} Tage"
    observations=dataset if dataset is not None else snapshot_observations(snapshot)
    pv_source={'source':'ha_solarforecast_ratio'}
    if config.get('pv_forecast_source')=='openmeteo_radiation':
        pv_source=apply_radiation(data,snapshot,observations,radiation_history)
    # Without the radiation model, missing HA PV totals would silently mean zero PV.
    if pv_source.get('source')!='openmeteo_radiation' and data.get('ha_pv_forecast_missing_days'):
        raise ValueError('No PV forecast available for '+', '.join(data['ha_pv_forecast_missing_days']))
    rows=[Interval(**r) for r in data['intervals']]

    calibration=snapshot.get('battery_calibration') or {}
    measured=config.get('efficiency_source')=='measured' and calibration.get('valid')
    discharge_eff=calibration['discharge_efficiency'] if measured else config['discharge_efficiency']
    charge_eff=calibration['charge_efficiency'] if measured else config['roundtrip_efficiency']/config['discharge_efficiency']
    efficiency={'source':'measured' if measured else 'configured','charge_efficiency':charge_eff,'discharge_efficiency':discharge_eff,
                'roundtrip':charge_eff*discharge_eff,'measurement':calibration}
    params=Params(capacity_kwh=data['planning_capacity_kwh'],reserve_kwh=data['reserve_kwh'],
        initial_kwh=data['initial_kwh'],pv_coupling='dc',max_charge_kw=config['max_charge_kw'],
        max_discharge_kw=config['max_discharge_kw'],discharge_efficiency=discharge_eff,
        charge_efficiency=charge_eff,energy_step_kwh=config['energy_step_kwh'],
        grid_charge_limit_kwh=data['grid_charge_limit_kwh'],decision_block_minutes=config.get('decision_block_minutes',30),
        terminal_value_eur_kwh=0.,switch_cost_eur=float(config.get('switch_cost_eur',0.)))
    tail=build_tail(snapshot,data,rows[-1].end,observations,
                    price_history or [],days=int(config.get('forecast_tail_days',7)),evidence=price_evidence,
                    price_model=config.get('tail_price_model','flat_median'),
                    persistence=float(config.get('tail_price_persistence',.7)),
                    price_floor=config.get('tail_price_floor_eur_kwh'),
                    weather_weight=float(config.get('tail_pv_weather_weight',0.)),
                    pv_model=config.get('tail_pv_model','hourly_median28'),
                    radiation_pv={float(k):v for k,v in pv_source.get('hours',{}).items()},
                    long_days=int(config.get('tail_price_long_days',28)),weekday=bool(config.get('tail_price_weekday',False)),
                    load_estimator=config.get('load_estimator','median'),load_half_life=float(config.get('load_half_life_days',7)))
    curve=continuation_curve(scenario_rows(tail),params,mean_weight=float(config.get('tail_scenario_mean_weight',.5)),end_value_eur_kwh=tail_end_value(config))
    params=replace(params,terminal_value_curve=tuple(map(tuple,curve)))
    candidate=optimize(rows,params)
    policy=choose_operation(rows,params,candidate,config)
    result=idle_charge_as_hold(policy['plan'],rows,params)
    valid_until=rows[-1].end
    week=schedules(rows,result['modes'],valid_until)
    charge,serve=schedule_payloads(week)
    # Evaluate the SAME central policy under alternative PV quantities; these are
    # sensitivity cases, NOT confidence intervals or measured savings.
    sensitivity=[]
    for multiplier in (.65,1.35):
        altered=[replace(r,pv_kwh=r.pv_kwh*multiplier) for r in rows]
        actual=_replay(altered,result['modes'],params)
        sensitivity_baseline=_replay(altered,['serve']*len(rows),params)
        sensitivity.append({'pv_multiplier':multiplier,'fixed_policy_cost_eur':actual['cost_eur'],
                            'savings_vs_serve_baseline_eur':sensitivity_baseline['cost_eur']-actual['cost_eur']})
    target=max([min(f['terminal_kwh'],data['grid_charge_limit_kwh'])/data['nominal_capacity_kwh']*100
                for f in result['intervals'] if f['charger_ac_kwh']>1e-10] or [0])
    target=min(math.floor(data['grid_charge_limit_kwh']/data['nominal_capacity_kwh']*100+1e-9),math.ceil(target-1e-9))
    permission=snapshot['states'].get('input_boolean.'+settings.current().helpers()['permission'])
    installed=bool(config.get('controller_installed',False)) or permission is not None   # the release switch exists: a controller is installed
    enabled=installed and (permission or {}).get('state')=='on'
    return {'created_at':datetime.now(TZ).isoformat(),'mode':'live' if enabled else 'shadow','control_installed':installed,'control_enabled':enabled,
      'valid_until':valid_until.isoformat(),'snapshot_collected_at':snapshot['collected_at'],
      'plan':result,'charge_schedule':charge,'serve_schedule':serve,
      'target_soc':max(0,min(100,target)),'pv_sensitivity':sensitivity,
      'terminal_value':{'method':'uncertain_recharge_aware_continuation_curve','curve':curve,
        'legacy_fixed_credit_ignored':True,'no_tail_end_credit':True},
      'multiday_forecast':tail,
      'operating_policy':{k:v for k,v in policy.items() if k!='plan'},
      'optimization_candidate':candidate,
      'forecast_baseline':baseline,'forecast_model':forecast_model,'pv_source':pv_source,
      'device_consumption':snapshot.get('device_consumption'),'efficiency':efficiency,
      'ev':ev_charging.evaluate(result['intervals'],snapshot.get('ev_charging'),config),
      'inputs':{k:v for k,v in data.items() if k not in ('intervals',)},
      'assumptions':config['notes']}

def report(plan):
    result=plan['plan'];comp=result['comparison'];inputs=plan['inputs']
    total_charge=math.fsum(f['charger_ac_kwh'] for f in result['intervals'])
    lines=['Hausakku · HA-Steuerung freigegeben' if plan.get('control_enabled') else 'Hausakku · Schattenbetrieb (keine Hardware-Schaltung)',
      f"Akku {inputs['soc']:.0f}% / {inputs['initial_kwh']:.2f} kWh. Plan bis {datetime.fromisoformat(plan['valid_until']).strftime('%d.%m. %H:%M')}.",
      f"Netzladen: {total_charge:.2f} kWh; simulierter Kassen-Vorteil im bekannten Preishorizont ggü. durchgehendem WR: {comp['total_savings_eur']:.2f} €.",
      f"Davon Aufheben {comp['hold_benefit_eur']:.2f} €, zusätzliche Netzladung {comp['incremental_grid_charge_benefit_eur']:.2f} €."]
    if 'operating_policy' in plan:
        policy=plan['operating_policy']
        lines.append(policy['reason'])
        if policy.get('carryover_curve_active'):
            lines.append(f"Zusätzlich geschätzter Übernahme-Vorteil {comp['estimated_carryover_benefit_eur']:+.2f} €; Zielwert-Vorteil gesamt {comp['objective_savings_eur']:+.2f} €. Keine gemessene Ersparnis; abnehmender Wert weiterer kWh, kein fixer Restpreis.")
            tail=plan['multiday_forecast']
            lines.append(f"Mehrtagessicht {tail['days']} Tage: {tail['price_model']}, {tail['price_training_intervals']} Preisintervalle (Tibber-Archiv + Börsen-Rekonstruktion); rückgerechnete Baseline, Szenarien kein Konfidenzintervall. Nur bekannte Preise erlauben Schaltfenster.")
            shaped=tail.get('shaped_price_model')
            if shaped:
                levels={}
                for r,p in zip(tail['rows'],tail['baseline_prices']):levels.setdefault(r['start'][5:10],[]).append(p)
                parts=[f"{d} {sum(v)/len(v)*100:.1f}" for d,v in levels.items()]
                lines.append(f"Preisniveau Folgetage (Tagesverlauf + Niveau, Persistenz {shaped['persistence']:.2f}): {'; '.join(parts)} ct; "
                             f"letzter bekannter Tag {shaped['known_level']*100:.1f} ct, Median {shaped.get('long_days',28)} Tage {shaped['long_level']*100:.1f} ct"
                             +(", mit Wochentagseffekt." if any(shaped.get('weekday_offsets',[])) else "."))
            source=plan.get('price_history_source',{})
            if source.get('reconstructed_intervals'):
                cal=source['calibration']
                lines.append(f"Preisverlauf: {source['reconstructed_intervals']} Viertelstunden aus Börsenpreisen rekonstruiert (Tibber = {cal['fixed_eur_kwh']*100:.2f} ct + {cal['factor']:.3f} × Börse, max. Abweichung {cal['max_error_eur_kwh']*100:.3f} ct auf {cal['pairs']} Vergleichswerten).")
            elif source.get('calibration') or source.get('warning'):
                lines.append('Preisverlauf: keine Rekonstruktion ('+(source.get('warning') or source['calibration']['reason'])+'); nur echtes Tibber-Archiv.')
            adjustments=tail.get('weather_adjustments',{})
            if adjustments:
                seasonal=any(v.get('method')=='seasonal_quantile' for v in adjustments.values())
                parts=[f"{d[5:]} {'Saison' if seasonal else 'Historie'} {v['baseline_pv_kwh']:.1f}→DWD {v['weather_low_pv_kwh']:.1f} kWh ({v['mean_cloud_coverage']:.0f}% Wolken)" for d,v in sorted(adjustments.items())]
                lines.append(('PV Folgetage (gleicher Sonnenstand, DWD-Quantil unkalibriert): ' if seasonal else 'PV-Szenario (DWD-Niedrig, unkalibriert): ')+'; '.join(parts[:3]))
            elif tail.get('weather_warning'):
                lines.append('DWD-Wetterhinweis: '+tail['weather_warning'])
        elif policy.get('terminal_value_eur_kwh',0)>0:
            end_kwh=result['terminal_kwh']
            tv=policy['terminal_value_eur_kwh'];hint=''
            meta=plan.get('terminal_value',{})
            if meta and abs(meta.get('configured_eur_kwh',tv)-tv)>1e-9:
                hint=(f" (aus {meta['configured_eur_kwh']*100:.0f} c wegen PV-Überschuss "
                      f"{meta.get('pv_kwh_per_day',0):.1f} kWh/Tag vs. Last {meta.get('load_kwh_per_day',0):.1f} kWh/Tag gedämpft)")
            lines.append(f"Übernahmewert {tv*100:.0f} c/kWh{hint}: Netzladung bewertet auch Energie, die erst nach dem Preishorizont verbraucht wird. Akku am Horizont-Ende {end_kwh:.2f} kWh (Restwert {end_kwh*tv:.2f} €), Mehrwert Netzladung inkl. Übernahmewert {policy['candidate_incremental_grid_charge_objective_eur']:.2f} €.")
        if policy['reason_code']=='gain_below_threshold':
            lines.append(f"Ungenutzter Rechenvorteil {policy['candidate_savings_eur']:.2f} EUR liegt unter {policy['minimum_savings_eur']:.2f} EUR Eingriffsschwelle.")
    for mode,label in [('charge_schedule','Laden'),('serve_schedule','Versorgen')]:
        windows=[f"{w['data']['plan_date'][5:]} {w['from']}–{w['to']}" for day in DAYS for w in plan[mode][day]]
        lines.append(label+': '+('; '.join(windows) if windows else 'kein Fenster'))
    source=plan.get('pv_source',{})
    if source.get('source')=='openmeteo_radiation':
        fits=source['fits'];first=min(fits)
        lines.append(f"PV-Prognose: Open-Meteo-Strahlung, kalibriert auf eigene Messwerte ({fits[first]['training_days']} Tage gleichen Sonnenstands, {fits[first]['matched_from']}–{fits[first]['matched_to']}). "
                     +'; '.join(f"{d[5:]} {v:.1f} kWh" for d,v in sorted(plan['inputs']['pv_totals_corrected_kwh'].items()))+'.')
    else:
        if source.get('warning'):lines.append(f"PV-Prognose: Open-Meteo nicht verwendet ({source['warning']}); HA-Prognose mit Faktor.")
        lines.append(f"PV-Korrektur: Faktor {inputs['pv_calibration'].get('applied_factor',inputs['pv_calibration']['factor']):.2f} aus {inputs['pv_calibration']['pairs']} Vergleichstagen; Tagesverlauf weiterhin historisch.")
    if plan.get('forecast_learning_enabled'):
        meta=plan.get('forecast_model',{})
        lines.append(public_model_summary(meta))
        coverage=meta.get('coverage',{})
        if coverage:
            lines.append(f"Lerndaten: {coverage.get('complete_load_days',0)} vollständige Verbrauchstage, {coverage.get('complete_pv_days',0)} PV-Tage, {coverage.get('pv_pairs',0)} echte PV/Prognose-Paare.")
        if plan.get('forecast_learning_error'):
            lines.append(f"Lernlauf fehlgeschlagen ({plan['forecast_learning_error']}); bisheriges Verfahren bleibt aktiv.")
        audit=plan.get('forecast_audit',{})
        if audit.get('status')=='snapshot_replay_not_archived':
            lines.append('Snapshot-Wiederholung: keine neue echte Prognose im Archiv.')
        elif not audit.get('scored_targets'):
            lines.append('Prognosearchiv aktiv; noch keine abgeschlossenen Prognoseziele mit vollständigen Ist-Daten bewertet.')
        else:
            parts=[]
            for kind,label in [('load_hour','Verbrauch kWh/h'),('pv_day','PV kWh/Tag')]:
                if kind in audit.get('metrics',{}):
                    m=audit['metrics'][kind];parts.append(f"{label}: MAE {m['mae_kwh']:.2f} aus {m['count']} Zielen")
            lines.append('Gemessene Prognoseabweichung: '+('; '.join(parts) or 'Stunden-PV-Auswertung verfügbar')+'.')
    lines.append('HA-Schedules zurückgelesen und geprüft.' if plan.get('publication',{}).get('verified') else 'Nur lokal berechnet, nicht in HA veröffentlicht.')
    lines.append(('HA-Steuerung installiert; Freigabe '+('an.' if plan.get('control_enabled') else 'aus.')) if plan.get('control_installed') else 'Keine Steuerung gefunden (Freigabe-Schalter fehlt): Der Plan wird nicht automatisch ausgeführt, das Add-on schaltet selbst keine Geräte.')
    return '\n'.join(lines)

def _windows(intervals,mode):
    out=[]
    for f in intervals:
        if f['mode']!=mode:continue
        if out and out[-1][1]==f['start']:out[-1][1]=f['end']
        else:out.append([f['start'],f['end']])
    return [f"{datetime.fromisoformat(a).strftime('%d.%m. %H:%M')}–{datetime.fromisoformat(b).strftime('%H:%M')}" for a,b in out]


def plan_summary(plan):
    result=plan['plan'];iv=result['intervals']
    return {'charge_kwh':round(math.fsum(f['charger_ac_kwh'] for f in iv),2),'charge':_windows(iv,'charge'),
            'serve':_windows(iv,'serve'),'target_soc':plan.get('target_soc'),'reason':plan['operating_policy']['reason_code'],
            'end_kwh':round(result['terminal_kwh'],2),'created_at':plan.get('created_at')}


def _actual_day(dataset,day):
    rows=[r for r in (dataset or {}).get('hours',[]) if datetime.fromtimestamp(r['start'],TZ).date()==day]
    if len(rows)<23 or any(r.get('pv_kwh') is None or r.get('load_kwh') is None for r in rows):return None
    return sum(r['pv_kwh'] for r in rows),sum(r['load_kwh'] for r in rows)


def flex_tips(plan,hours=3):
    """Deterministic hints for shiftable loads (washing, dishwasher, vehicle) from KNOWN prices only."""
    iv=plan['plan']['intervals'];out=[]
    fmt=lambda a,b:f"{('Mo','Di','Mi','Do','Fr','Sa','So')[datetime.fromisoformat(a).weekday()]} {datetime.fromisoformat(a).strftime('%H:%M')}–{datetime.fromisoformat(b).strftime('%H:%M')}"
    hourly={}
    for f in iv:
        h=datetime.fromisoformat(f['start']).replace(minute=0,second=0,microsecond=0).isoformat()
        hourly.setdefault(h,[]).append(f['price_eur_kwh'])
    keys=sorted(hourly);means=[sum(hourly[k])/len(hourly[k]) for k in keys]
    blocks=[]
    for i in range(len(keys)-hours+1):
        blocks.append((sum(means[i:i+hours])/hours,i))
    chosen=[]
    for price,i in sorted(blocks):
        if all(abs(i-j)>=hours for _,j in chosen):chosen.append((price,i))
        if len(chosen)==2:break
    if chosen:
        end=lambda i:(datetime.fromisoformat(keys[i+hours-1])+timedelta(hours=1)).isoformat()
        out.append(f"Günstigste {hours}-Stunden-Blöcke (Wäsche/Spülmaschine): "+'; '.join(f"{fmt(keys[i],end(i))} Ø {p*100:.1f} ct" for p,i in sorted(chosen,key=lambda x:x[1])))
    floor=min(f['price_eur_kwh'] for f in iv)
    cheap=[f for f in iv if f['price_eur_kwh']<=floor+.01]
    spans=[]
    for f in cheap:
        if spans and spans[-1][1]==f['start']:spans[-1][1]=f['end']
        else:spans.append([f['start'],f['end']])
    long=[x for x in spans if datetime.fromisoformat(x[1])-datetime.fromisoformat(x[0])>=timedelta(hours=1)]
    if long:out.append(f"Stunden nahe Tiefstpreis {floor*100:.1f} ct (Fahrzeug laden): "+'; '.join(fmt(a,b) for a,b in long[:3]))
    spill=[f for f in iv if f['spill_dc_kwh']>1e-3]
    if spill:out.append(f"PV-Überschuss erwartet ({sum(f['spill_dc_kwh'] for f in spill):.1f} kWh, Akku voll): guter Zeitpunkt für Fahrzeug/Wäsche "+fmt(spill[0]['start'],spill[-1]['end']))
    serve=_windows(iv,'serve')
    if serve:out.append('Große Verbraucher (Fahrzeug, Trockner) nicht in Versorgen-Fenstern starten, sonst leert der WR den Akku dafür: '+', '.join(serve))
    return out


def llm_facts(plan,previous=None,dataset=None):
    """Compact deterministic facts for the LLM summary. Every number is computed here."""
    result=plan['plan'];iv=result['intervals'];inputs=plan['inputs'];params=result['params']
    now=summary=plan_summary(plan)
    roundtrip=params['charge_efficiency']*params['discharge_efficiency']
    lines=['=== FAKTEN FÜR DIE ZUSAMMENFASSUNG (berechnet, nicht ändern) ===']
    published=plan.get('publication',{}).get('verified')
    lines.append(f"Veröffentlicht und zurückgelesen: {'ja' if published else 'NEIN (nur berechnet)'}; gültig bis {datetime.fromisoformat(plan['valid_until']).strftime('%d.%m. %H:%M')}.")
    lines.append(f"Akku jetzt {inputs['soc']:.0f} % ({inputs['initial_kwh']:.1f} kWh von {inputs['nominal_capacity_kwh']:.0f}); am Ende des bekannten Preiszeitraums {result['terminal_kwh']:.1f} kWh.")
    if summary['charge_kwh']>0:
        charged=[f['price_eur_kwh'] for f in iv if f['charger_ac_kwh']>1e-9]
        price=max(charged)
        lines.append(f"Netzladen: {summary['charge_kwh']:.1f} kWh bis Ziel-SOC {summary['target_soc']} %, Fenster {', '.join(summary['charge'])}, höchster Ladepreis {price*100:.1f} ct.")
        lines.append(f"Gewinnschwelle: Ladestrom kostet effektiv {price/roundtrip*100:.1f} ct je später im Haus genutzter kWh ({price*100:.1f} ct / {roundtrip*100:.0f} % Wirkungsgrad); Laden lohnt, wenn er später Stunden über diesem Wert ersetzt.")
    else:lines.append('Netzladen: nein.')
    lines.append('Versorgen aus Akku/PV: '+(', '.join(summary['serve']) or 'kein Fenster')+'; in den Lade- und Aufheben-Zeiten ist der WR aus, das Haus läuft dann aus dem Netz und die PV geht in den Akku.')
    days={}
    for f in iv:days.setdefault(f['start'][:10],[]).append(f['price_eur_kwh'])
    known_load=math.fsum(f['load_kwh'] for f in iv);known_pv=math.fsum(f['pv_kwh'] for f in iv)
    house_grid=math.fsum(f['house_grid_kwh'] for f in iv);served=math.fsum(f['served_ac_kwh'] for f in iv)
    lines.append(f"Bekannter Preiszeitraum bis {datetime.fromisoformat(plan['valid_until']).strftime('%d.%m. %H:%M')}: erwarteter Hausverbrauch {known_load:.1f} kWh, davon {house_grid:.1f} kWh aus dem Netz und {served:.1f} kWh aus Akku/PV (nur im Versorgen-Fenster); erwartete PV {known_pv:.1f} kWh, die tagsüber in den Akku geht.")
    lines.append('Bekannte Tibber-Preise: '+'; '.join(f"{d[8:10]}.{d[5:7]}. {min(v)*100:.1f}–{max(v)*100:.1f} ct (Mittel {sum(v)/len(v)*100:.1f})" for d,v in days.items())+'.')
    tail=plan.get('multiday_forecast',{});tdays={}
    for r in tail.get('rows',[]):
        d=tdays.setdefault(r['start'][:10],{'p':[],'pv':0.,'load':0.});d['p'].append(r['price_eur_kwh']);d['pv']+=r['pv_kwh'];d['load']+=r['load_kwh']
    if tdays:
        lines.append('Erwartung Folgetage (Schätzung, keine Schaltfreigabe): '+'; '.join(
            f"{('Mo','Di','Mi','Do','Fr','Sa','So')[datetime.fromisoformat(d).weekday()]} {datetime.fromisoformat(d).strftime('%d.%m.')} Preis Ø {sum(v['p'])/len(v['p'])*100:.0f} ct (max {max(v['p'])*100:.0f}), PV {v['pv']:.1f} kWh, Verbrauch {v['load']:.1f} kWh"
            for d,v in tdays.items())+'.')
    source=plan.get('pv_source',{})
    pv=inputs.get('pv_totals_corrected_kwh',{})
    lines.append(f"PV-Prognose bekannte Tage ({'Open-Meteo kalibriert' if source.get('source')=='openmeteo_radiation' else 'HA-Prognose × Faktor'}): "+'; '.join(f"{d[8:10]}.{d[5:7]}. {v:.1f} kWh" for d,v in sorted(pv.items()))+'.')
    yesterday=datetime.fromisoformat(plan['created_at']).date()-timedelta(days=1)
    actual=_actual_day(dataset,yesterday)
    if actual:lines.append(f"Gestern gemessen: PV {actual[0]:.1f} kWh, Hausverbrauch {actual[1]:.1f} kWh (ohne Fahrzeugladen).")
    devices=plan.get('device_consumption')
    if devices:
        for key,label in (('yesterday','Verbraucher gestern'),('today','Verbraucher heute bis '+datetime.fromisoformat(devices['today_until']).strftime('%H:%M'))):
            top=sorted(((v,n) for n,v in devices[key].items() if v>=.1),reverse=True)[:7]
            if top:lines.append(label+' (Energie-Dashboard, Geräte können sich überschneiden): '+', '.join(
                f"{n} {v:.1f} kWh" for v,n in top)+'.')
    comp=result['comparison']
    lines.append(f"Simuliert, nicht gemessen: Kasse im bekannten Zeitraum {comp['total_savings_eur']:+.2f} €, geschätzter Wert der mitgenommenen Energie {comp['estimated_carryover_benefit_eur']:+.2f} €, zusammen {comp['objective_savings_eur']:+.2f} € ggü. durchgehendem WR.")
    if previous:
        changed=previous.get('charge')!=summary['charge'] or previous.get('serve')!=summary['serve']
        lines.append(f"Vorheriger veröffentlichter Plan ({datetime.fromisoformat(previous['created_at']).strftime('%d.%m. %H:%M')}): Netzladen {previous['charge_kwh']:.1f} kWh, Versorgen {', '.join(previous['serve']) or 'kein Fenster'}; "
                     +('Fahrplan GEÄNDERT.' if changed else 'Fahrplan unverändert.'))
    eff=plan.get('efficiency',{});m=eff.get('measurement') or {}
    if eff:
        lines.append(f"Wirkungsgrad: {'gemessen' if eff['source']=='measured' else 'angenommen'} {eff['roundtrip']*100:.0f} % hin und zurück"
                     +(f" (Messung {m['roundtrip']*100:.0f} % aus {m['charge_hours']} Lade- und {m['discharge_hours']} Entladestunden"+('' if m.get('valid') else ', noch nicht übernommen: '+m.get('reason',''))+')' if m.get('roundtrip') else '')+'.')
    hints=[]
    if source.get('warning'):hints.append('PV-Rückfall: '+source['warning'])
    price=plan.get('price_history_source',{})
    if price.get('warning'):hints.append('Preisverlauf: '+price['warning'])
    elif price.get('calibration') and not price['calibration'].get('valid'):hints.append('Tibber-Formel passt nicht mehr ('+price['calibration']['reason']+')')
    if plan.get('forecast_learning_error'):hints.append('Lernlauf fehlgeschlagen ('+plan['forecast_learning_error']+')')
    if inputs.get('ha_pv_forecast_missing_days'):hints.append('HA-PV-Prognose fehlte, Open-Meteo verwendet')
    if plan.get('ev_publication') and not plan['ev_publication'].get('verified'):hints.append('Fahrzeug-Ladefenster konnte nicht in HA geschrieben werden ('+plan['ev_publication'].get('error','?')+'); Akku-Plan nicht betroffen')
    ev=plan.get('ev') or {}
    ev_helper_name=settings.current().entity('ev_window_helper',required=False)
    if not ev_helper_name:ev_where='Kein Zeitplan-Helfer eingerichtet, daher nicht in HA eingetragen.'
    elif (plan.get('ev_publication') or {}).get('verified'):ev_where=f'In HA als schedule.{ev_helper_name} eingetragen.'
    else:ev_where=f'Nicht in HA eingetragen (nur im Plan berechnet).'
    hm=lambda t:datetime.fromisoformat(t).strftime('%H:%M');day=lambda t:('Mo','Di','Mi','Do','Fr','Sa','So')[datetime.fromisoformat(t).weekday()]
    if ev.get('status')=='ok':
        lines.append(f"Fahrzeug: SoC {ev['soc']:.0f} % → Ziel {ev['target_soc']:.0f} % = {ev['need_kwh']:.1f} kWh am Netz ({ev['kwh_per_percent']:.2f} kWh je %, {ev['per_percent_source']}), bei {ev['power_kw']:.1f} kW ({ev['power_source']}) etwa {ev['duration_h']:.1f} h"+('' if ev.get('plugged') else '; Stecker aktuell NICHT gesteckt')+'.')
        lines.append(f"Fahrzeug-Ladefenster (günstigster Block, nicht in Versorgen-Fenstern des Akkus): {day(ev['start'])} {hm(ev['start'])}–{hm(ev['end'])}, Ø {ev['mean_price_eur_kwh']*100:.1f} ct, ca. {ev['cost_eur']:.2f} €. Gleich günstig zwischen {day(ev['flex_start'])} {hm(ev['flex_start'])} und {day(ev['flex_end'])} {hm(ev['flex_end'])}. {ev_where} Start in der Fahrzeug-App (Zeitgesteuertes Laden).")
    elif ev.get('status')=='full':
        lines.append(f"Fahrzeug: SoC {ev['soc']:.0f} % ist am Ziel ({ev['target_soc']:.0f} %), kein Laden nötig.")
    elif ev:
        lines.append('Fahrzeug-Ladefenster nicht berechnet: '+{'unknown_soc':ev.get('reason','SoC unbekannt'),'no_block':'kein ausreichend langer Block ohne Versorgen-Fenster im bekannten Preiszeitraum','no_power':'Ladeleistung unbekannt'}.get(ev['status'],ev['status'])+'.')
    for tip in flex_tips(plan):lines.append('Tipp-Daten: '+tip+'.')
    lines.append('Rückfälle/Hinweise: '+('; '.join(hints) if hints else 'keine')+'.')
    return '\n'.join(lines)


STAGE=['Start']


def published_modes(plan):
    return [[f['start'],f['mode']] for f in plan['plan']['intervals']]


def target_matters(plan,previous):
    """The target SOC only acts while the charger can run, so it is irrelevant without a charge plan."""
    planned=math.fsum(f['charger_ac_kwh'] for f in plan['plan']['intervals'])
    return previous.get('charge_kwh',0)>=IDLE_CHARGE_KWH or planned>=IDLE_CHARGE_KWH


def schedule_changed(plan,previous,now):
    """True when the effective future mode, expiry or target differs from the last publication.
    Starts of the current interval move with every run and are ignored."""
    if not previous or 'modes' not in previous:return True
    if previous.get('valid_until')!=plan['valid_until']:return True
    if previous.get('target_soc')!=plan['target_soc'] and target_matters(plan,previous):return True
    def future(modes):
        out={}
        for start,mode in modes:
            t=datetime.fromisoformat(start).timestamp()
            slot=math.floor(t/900)*900
            if slot>=now.timestamp():out[slot]=mode
        return out
    old,new=future(previous['modes']),future(published_modes(plan))
    return any(old.get(t)!=m for t,m in new.items())


def publication_decision(plan,previous,now,min_gain=.05):
    """Hysteresis for hourly republishing. Each publication briefly invalidates the plan and
    costs about five charging minutes, so only publish when the new plan beats CONTINUING the
    old one under the same fresh data by min_gain. Safety-relevant changes always publish."""
    if not schedule_changed(plan,previous,now):return {'publish':False,'reason':'Fahrplan unverändert'}
    if not previous or 'modes' not in previous:return {'publish':True,'reason':'kein vergleichbarer veröffentlichter Plan'}
    if previous.get('valid_until')!=plan['valid_until']:return {'publish':True,'reason':'neuer Gültigkeitszeitraum (neue Preise)'}
    if previous.get('target_soc')!=plan['target_soc'] and target_matters(plan,previous):return {'publish':True,'reason':'Ziel-SOC geändert'}
    old={math.floor(datetime.fromisoformat(t).timestamp()/900)*900:m for t,m in previous['modes']}
    iv=plan['plan']['intervals']
    modes=[old.get(math.floor(datetime.fromisoformat(f['start']).timestamp()/900)*900) for f in iv]
    if None in modes:return {'publish':True,'reason':'alter Plan deckt den Zeitraum nicht ab'}
    # An open old charge window where nothing is planned could charge at higher prices.
    if any(m=='charge' and f['charger_ac_kwh']<=1e-9 for m,f in zip(modes,iv)):
        return {'publish':True,'reason':'alter Plan hätte ungeplant nachladen können'}
    rows=[Interval(datetime.fromisoformat(f['start']),datetime.fromisoformat(f['end']),f['price_eur_kwh'],f['load_kwh'],f['pv_kwh']) for f in iv]
    params=Params(**plan['plan']['params'])
    gain=_replay(rows,modes,params)['objective_eur']-plan['plan']['objective_eur']
    if gain<min_gain:return {'publish':False,'reason':f'Vorteil {gain*100:.1f} ct unter Schwelle {min_gain*100:.0f} ct','gain_eur':gain}
    return {'publish':True,'reason':f'Vorteil {gain*100:.1f} ct gegenüber altem Plan','gain_eur':gain}


def significant_change(plan,previous):
    """Worth a message: charge decision flips, >=1.5 kWh charge change or >=1 h serve change."""
    if not previous:return True
    now=plan_summary(plan)
    hours=lambda modes,kind:sum(1 for t,m in modes if m==kind and datetime.fromisoformat(t).timestamp()>=datetime.fromisoformat(plan['created_at']).timestamp())/4
    serve_old=hours(previous.get('modes',[]),'serve');serve_new=hours(published_modes(plan),'serve')
    return ((previous['charge_kwh']>0)!=(now['charge_kwh']>0) or abs(previous['charge_kwh']-now['charge_kwh'])>=1.5
            or abs(serve_old-serve_new)>=1)


def change_message(plan,previous,reason):
    now=plan_summary(plan);inputs=plan['inputs']
    lines=[f"🔄 Hausakku-Plan nachgeführt ({datetime.fromisoformat(plan['created_at']).strftime('%H:%M')}, Akku {inputs['soc']:.0f} %): {reason}"]
    lines.append(f"Laden: {now['charge_kwh']:.1f} kWh "+(('('+', '.join(now['charge'])+')') if now['charge'] else '')
                 +(f" – vorher {previous['charge_kwh']:.1f} kWh" if previous else ''))
    lines.append('Versorgen: '+(', '.join(now['serve']) or 'kein Fenster')+((' – vorher '+(', '.join(previous['serve']) or 'kein Fenster')) if previous else ''))
    lines.append(f"Ziel-SOC {now['target_soc']} %, gültig bis {datetime.fromisoformat(plan['valid_until']).strftime('%d.%m. %H:%M')}.")
    return '\n'.join(lines)

async def run(args):
    replan=getattr(args,'replan',False)
    started=time.monotonic();config=load_config()
    STAGE[0]='Datenabruf aus HA'
    snapshot=json.loads((BASE/'state/snapshot.json').read_text()) if args.from_snapshot else await collect()
    STAGE[0]='Berechnung'
    # Dry runs overwrite plan.json; the last VERIFIED publication is kept separately.
    previous=None
    try:previous=json.loads((BASE/'state/last_published.json').read_text())
    except Exception:previous=None
    if args.publish:
        age=(datetime.now(TZ)-datetime.fromisoformat(snapshot['collected_at'])).total_seconds()
        if age>300 or age< -30:raise ValueError('Snapshot too old for publication')
    dataset=None;artifact=None;learning_error=None
    price_path=BASE/'state/multiday_audit.sqlite'
    if not args.from_snapshot:
        seed_price_archive(price_path,BASE/'state/snapshots',snapshot['collected_at'])
        archive_prices(price_path,snapshot)
        archive_weather(price_path,snapshot)
        archive_radiation(price_path,snapshot)
    learning_enabled=bool(config.get('forecast_learning_enabled',False))
    if learning_enabled and not args.from_snapshot:
        try:dataset,artifact=await refresh_learning(snapshot,BASE/'state/training')
        except Exception as exc:
            # Fallback is intentional; never print transport exceptions/URLs.
            learning_error=type(exc).__name__
    if dataset is None:
        dataset_path=BASE/'state/training/annual_dataset.json'
        dataset=json.loads(dataset_path.read_text()) if dataset_path.exists() else snapshot_observations(snapshot)
    evidence=score_issues(price_path,dataset,snapshot['collected_at']) if not args.from_snapshot else None
    radiation_history=None;history_path=BASE/'state/training/openmeteo_history.json'
    if config.get('pv_forecast_source')=='openmeteo_radiation':
        try:
            radiation_history=load_history(history_path) if args.from_snapshot else await asyncio.to_thread(
                refresh_history,history_path,config['openmeteo_latitude'],config['openmeteo_longitude'],datetime.now(TZ).date())
        except Exception:
            # Stale cache is still valid calibration data; a fetch error must not stop planning.
            radiation_history=load_history(history_path)
    archive=read_prices(price_path,snapshot['collected_at']);price_history=archive;price_source={'reconstructed_intervals':0}
    if config.get('tail_price_history')=='energy_charts':
        spot_path=BASE/'state/training/spot_prices.json'
        try:spot=spot_prices.load(spot_path) if args.from_snapshot else await asyncio.to_thread(spot_prices.refresh,spot_path,datetime.now(TZ).date(),zone=settings.current().data['prices'].get('bidding_zone') or 'DE-LU')
        except Exception as exc:
            spot=spot_prices.load(spot_path);price_source['warning']='exchange price refresh failed ('+type(exc).__name__+')'
        if spot:
            calibration=spot_prices.calibrate(spot,archive)
            extra=spot_prices.reconstructed_history(spot,calibration,archive)
            price_history=archive+extra
            price_source.update(calibration=calibration,reconstructed_intervals=len(extra))
    plan=compute_plan(snapshot,config,learning_artifact=artifact,dataset=dataset,
                      price_history=price_history,price_evidence=evidence,
                      radiation_history=radiation_history)
    plan['price_history_source']=price_source
    plan['forecast_learning_enabled']=learning_enabled
    if learning_error:plan['forecast_learning_error']=learning_error
    if args.publish:
        end=datetime.fromisoformat(plan['valid_until'])
        if end.timestamp()-datetime.now(TZ).timestamp()<4*3600:
            # Hourly replan keeps the still-valid published plan instead of failing.
            if replan:return None
            raise ValueError('Insufficient price horizon; wait for tomorrow prices')
        policy=plan['operating_policy']
        comp=plan['plan']['comparison']
        status=f"Fahrplan | {policy['reason_code']} | Kasse simuliert {comp['total_savings_eur']:+.2f} EUR"
        status+=f" | Uebernahme geschaetzt {comp['estimated_carryover_benefit_eur']:+.2f} EUR"
        status+=f" | {datetime.now(TZ).strftime('%d.%m. %H:%M')}"
        decision=publication_decision(plan,previous,datetime.now(TZ),float(config.get('replan_min_gain_eur',.05))) if replan else {'publish':True,'reason':'Tageslauf'}
        plan['publication_decision']=decision
        if not decision['publish']:
            plan['publication']={'verified':False,'skipped':decision['reason']}
        else:
            STAGE[0]='Veröffentlichung in HA'
            plan['publication']=await publish(plan['charge_schedule'],plan['serve_schedule'],end,plan['target_soc'],status)
            STAGE[0]='Nacharbeit nach Veröffentlichung'
    ev=plan.get('ev') or {}
    if args.publish and ev.get('status') in ('ok','full') and settings.current().entity('ev_window_helper',required=False):
        # Display helper only; failure must never touch the battery plan.
        written=BASE/'state/ev_window_written.json'
        try:
            last=json.loads(written.read_text()) if written.exists() else None
            if last!=ev['week']:
                STAGE[0]='Fahrzeug-Ladefenster'
                plan['ev_publication']=await publish_ev_window(ev['week'])
                written.write_text(json.dumps(ev['week'],indent=2))
            else:plan['ev_publication']={'verified':True,'unchanged':True}
        except Exception as exc:
            plan['ev_publication']={'verified':False,'error':type(exc).__name__}
        STAGE[0]='Nacharbeit nach Veröffentlichung'
    if not args.from_snapshot:
        rows=[Interval(datetime.fromisoformat(r['start']),datetime.fromisoformat(r['end']),r['price_eur_kwh'],r['load_kwh'],r['pv_kwh']) for r in plan['plan']['intervals']]
        zero_params=Params(**{**plan['plan']['params'],'terminal_value_eur_kwh':0.,'terminal_value_curve':()})
        zero_candidate=optimize(rows,zero_params)
        zero_policy=choose_operation(rows,zero_params,zero_candidate,config)['plan']
        shadow={}
        for label in ('candidate','baseline_tail'):
            tail=copy.deepcopy(plan['multiday_forecast'])
            for index,r in enumerate(tail['rows']):
                r['price_eur_kwh']=tail['candidate_prices'][index] if label=='candidate' else tail['baseline_prices'][index]
            curve=continuation_curve(scenario_rows(tail),zero_params,mean_weight=float(config.get('tail_scenario_mean_weight',.5)),end_value_eur_kwh=tail_end_value(config))
            shadow_params=replace(zero_params,terminal_value_curve=tuple(map(tuple,curve)))
            shadow[label]=choose_operation(rows,shadow_params,optimize(rows,shadow_params),config)['plan']
        plan['multiday_issue_id']=archive_issue(price_path,snapshot,plan['multiday_forecast'],plan['plan'],zero_policy,**shadow)
        plan['multiday_validation']=score_issues(price_path,dataset,snapshot['collected_at'])
        model=plan['multiday_forecast']
        version=hashlib.sha256(json.dumps(model,sort_keys=True,allow_nan=False).encode()).hexdigest()
        model_path=BASE/'state/training/multiday_models'/f'{version}.json'
        model_path.parent.mkdir(parents=True,exist_ok=True)
        if not model_path.exists():model_path.write_text(json.dumps(model,indent=2,allow_nan=False))
        plan['multiday_model_id']=version
    if learning_enabled:
        if args.from_snapshot:
            plan['forecast_audit']={'status':'snapshot_replay_not_archived'}
        else:
            if dataset is None:dataset=snapshot_observations(snapshot)
            audit_path=BASE/'state/forecast_audit.sqlite'
            plan['forecast_scoring']=score_forecasts(audit_path,dataset,datetime.now(TZ))
            plan['forecast_issue_id']=archive_forecast(audit_path,plan,snapshot)
            plan['forecast_audit']=audit_summary(audit_path)
    plan['runtime_seconds']=time.monotonic()-started
    state=BASE/'state';state.mkdir(exist_ok=True)
    temp=state/'plan.new.json';temp.write_text(json.dumps(plan,indent=2,allow_nan=False));temp.replace(state/'plan.json')
    (state/'report.txt').write_text(report(plan)+'\n')
    if plan.get('publication',{}).get('verified'):
        (state/'last_published.json').write_text(json.dumps({**plan_summary(plan),'modes':published_modes(plan),
            'valid_until':plan['valid_until']},indent=2))
    if replan:
        # Silent unless the published schedule changed noticeably; the caller forwards stdout only.
        if plan.get('publication',{}).get('verified') and significant_change(plan,previous):
            print(change_message(plan,previous,plan['publication_decision']['reason']+'.'))
        return plan
    print(report(plan))
    print();print(llm_facts(plan,previous,dataset))

async def fail_closed():
    try:
        async with connection() as ha:await expire(ha)
        return True
    except Exception:return False

def main():
    p=argparse.ArgumentParser();p.add_argument('--publish',action='store_true');p.add_argument('--from-snapshot',action='store_true')
    p.add_argument('--replan',action='store_true',help='hourly: publish only on schedule change, quiet output')
    args=p.parse_args()
    if args.replan:args.publish=True
    (BASE/'state').mkdir(exist_ok=True)
    with (BASE/'state/run.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            if not args.replan:print('Hausakku: Ein Lauf ist bereits aktiv.')
            return 0
        failures=BASE/'state/replan_failures.json'
        try:
            asyncio.run(run(args))
            if args.replan and failures.exists():failures.unlink()
            return 0
        except Exception as exc:
            # Only a failure DURING publication can leave half-written schedules; then fail closed.
            # Earlier failures keep the previously verified, date-bound plan, which expires on its own.
            invalidated=asyncio.run(fail_closed()) if args.publish and STAGE[0]=='Veröffentlichung in HA' else None
            # No raw transport exception/traceback: it can contain the private MCP URL.
            failure={'time':datetime.now(TZ).isoformat(),'error_class':type(exc).__name__}
            (BASE/'state/last_failure.json').write_text(json.dumps(failure,indent=2))
            if args.replan and invalidated is None:
                count=(json.loads(failures.read_text()).get('count',0) if failures.exists() else 0)+1
                failures.write_text(json.dumps({'count':count,'last':failure},indent=2))
                # Transient HA/network hiccups stay silent; the published plan remains valid.
                if count<3:return 0
                print(f"⚠️ Hausakku-Nachplanung schlägt seit {count} Läufen fehl ({type(exc).__name__}, Abbruch bei: {STAGE[0]}). Der zuletzt veröffentlichte Plan bleibt bis zu seinem Ablauf gültig.")
                return 0
            print('[CRON_FAILURE] Hausakku-Planer fehlgeschlagen ('+type(exc).__name__+', Abbruch bei: '+STAGE[0]+'). Kein neuer Plan freigegeben.',file=sys.stderr)
            if invalidated:
                print('HA-Zustand: bisheriger Plan wurde absichtlich UNGÜLTIG gesetzt. Die Steuerung fährt den sicheren Rückfall: keine Netzladung, nur WR. Der alte Plan gilt NICHT weiter.',file=sys.stderr)
            elif invalidated is False:
                print('HA-Zustand UNKLAR: Ungültigsetzen des alten Plans ist fehlgeschlagen. Bitte HA-Plan manuell prüfen.',file=sys.stderr)
            elif args.publish:
                print('HA-Zustand: Abbruch vor der Veröffentlichung, HA wurde nicht verändert. Der zuletzt veröffentlichte Plan gilt bis zu seinem Ablaufzeitpunkt weiter.',file=sys.stderr)
            return 1
if __name__=='__main__':sys.exit(main())
