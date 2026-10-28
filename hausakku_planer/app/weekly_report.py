#!/usr/bin/env python3
"""Weekly measured balance for the Qwen summary. Read-only towards HA; writes only state/.

Default: the last 7 complete local days ending at today's midnight.
Prints a fact block; a notifier can phrase it. No hardware access.
"""
import argparse,asyncio,json,math,sys
from datetime import datetime,timedelta
from pathlib import Path
import paths,settings
from collector import energy_map,vehicle_entities,body,device_label,normalize_statistics,vehicle_energy
from forecast import TZ
from forecast_audit import audit_summary
from ha_client import connection
from multiday import read_prices
from optimizer import Params
from planner import tail_end_value,load_config
import savings,spot_prices
BASE=paths.DATA
WEEKDAYS=('Mo','Di','Mi','Do','Fr','Sa','So')


def hourly_prices(path_archive,spot_path,until):
    """Hourly mean Tibber prices: real archive first, exact exchange reconstruction for gaps."""
    archive=read_prices(path_archive,until.isoformat())
    quarter={r['start']:r['price'] for r in archive}
    spot=spot_prices.load(spot_path)
    calibration=spot_prices.calibrate(spot,archive) if spot else {'valid':False}
    for r in spot_prices.reconstructed_history(spot or {},calibration,archive):quarter.setdefault(r['start'],r['price'])
    hours={}
    for t,p in quarter.items():hours.setdefault(math.floor(t/3600)*3600,[]).append(p)
    return {h:sum(v)/len(v) for h,v in hours.items() if len(v)==4},calibration


async def fetch(start,end):
    cfg=settings.current();ENERGY=energy_map(cfg);EVS=vehicle_entities(cfg)
    BATTERY=cfg.entity('battery_kwh')
    async with connection() as ha:
        energy=await ha.call('ha_get_history',source='statistics',entity_ids=list(ENERGY.values()),start_time=start.isoformat(),
                             end_time=end.isoformat(),period='hour',statistic_types=['change'],limit=1000)
        vehicles=({'entities':[]} if not EVS else await ha.call('ha_get_history',source='statistics',entity_ids=EVS,start_time=start.isoformat(),
                               end_time=end.isoformat(),period='hour',statistic_types=['change'],limit=1000))
        battery=await ha.call('ha_get_history',source='statistics',entity_ids=BATTERY,start_time=(start-timedelta(hours=1)).isoformat(),
                              end_time=end.isoformat(),period='hour',statistic_types=['mean'],limit=1000)
        devices=None
        try:
            prefs=await ha.call('ha_manage_energy_prefs',mode='get')
            entities=[d['stat_consumption'] for d in body(prefs).get('config',{}).get('device_consumption',[])]
            stats=await ha.call('ha_get_history',source='statistics',entity_ids=entities,start_time=start.isoformat(),
                                end_time=end.isoformat(),period='day',statistic_types=['change'],limit=100)
            totals={}
            for e in body(stats)['entities']:
                entry=next((d for d in body(prefs)['config']['device_consumption'] if d['stat_consumption']==e['entity_id']),{'stat_consumption':e['entity_id']})
                totals[device_label(entry)]=sum(normalize_statistics({'entities':[e]}).get(e['entity_id'],{}).values())
            devices=totals
        except Exception:
            devices=None
    return energy,vehicles,battery,devices


MIN_HOURS=24

class WeeklyError(ValueError):
    """A reason the balance cannot be made; the text holds only counts, so it is safe to report."""

def trailing_complete(hours,prices,start):
    """The latest unbroken block of hours with a known price and complete measurements. A new installation has no
    price archive for the whole week yet, so the balance then covers the shorter period it can stand behind."""
    ok=lambda h:h['start'] in prices and all(h.get(k) is not None and math.isfinite(h[k]) for k in h if k!='start' and k!='ev') and h.get('ev') is not None
    block=[]
    for h in sorted(hours,key=lambda r:r['start'],reverse=True):
        if not ok(h):break
        block.append(h)
    block.reverse()
    if len(block)<MIN_HOURS:
        missing={k:sum(1 for h in hours if h.get(k) is None) for k in sorted({k for h in hours for k in h if k!='start'})}
        raise WeeklyError('Nur %d lückenlose Stunden am Ende (nötig %d); von %d Stunden ohne Preis: %d, Messwert fehlt: %s'%(
            len(block),MIN_HOURS,len(hours),sum(1 for h in hours if h['start'] not in prices),
            ', '.join(k+' '+str(n) for k,n in missing.items() if n)))
    return block,(datetime.fromtimestamp(block[0]['start'],TZ) if len(block)<len(hours) else start)

def battery_at(battery,stamp):
    rows={float(r['start'])/1000:r.get('mean') for e in body(battery)['entities'] for r in e.get('statistics',[])}
    candidates=[v for t,v in rows.items() if v is not None and abs(t-stamp)<=3600]
    return float(candidates[0]) if candidates else None


def facts(result,week,devices,calibration,audit,history):
    r=result;f=lambda x:f"{x:+.2f} €"
    lines=['=== WOCHENFAKTEN HAUSAKKU (gemessen und nachgerechnet, nicht ändern) ===',
           f"Zeitraum: {WEEKDAYS[week[0].weekday()]} {week[0].strftime('%d.%m.')} bis {WEEKDAYS[(week[1]-timedelta(days=1)).weekday()]} {(week[1]-timedelta(days=1)).strftime('%d.%m.%Y')}; {r['hours']} vollständige Stunden"+(f", {r['skipped_hours']} Stunden ohne vollständige Daten ausgelassen" if r['skipped_hours'] else '')+'.',
           f"Stromkosten Haus (ohne Tesla/City El), tatsächlich: {r['actual_cost_eur']:.2f} €; ohne Akku-Steuerung (WR durchgehend an, nie Netzladen) nachgerechnet: {r['counterfactual_cost_eur']:.2f} €.",
           f"Gemessene Kassen-Ersparnis: {f(r['cash_saving_eur'])}.",
           f"Akku Wochenende: tatsächlich {r['end_kwh']:.1f} kWh, ohne Steuerung wären es {r['counterfactual_end_kwh']:.1f} kWh gewesen (Differenz {r['inventory_difference_kwh']:+.1f} kWh, vorsichtig bewertet {f(r['inventory_value_eur'])}).",
           f"Ersparnis inkl. Akkustand: {f(r['saving_incl_inventory_eur'])}.",
           f"Hausverbrauch {r['house_load_kwh']:.1f} kWh, PV {r['pv_kwh']:.1f} kWh."]
    if r['grid_charged_ac_kwh']>0.05:
        lines.append(f"Netzladen: {r['grid_charged_ac_kwh']:.1f} kWh zu Ø {r['mean_charge_price_eur_kwh']*100:.1f} ct.")
    if r['battery_served_ac_kwh']>0.05:
        lines.append(f"Akku/PV hat {r['battery_served_ac_kwh']:.1f} kWh ans Haus geliefert, in Stunden mit Ø {r['mean_served_price_eur_kwh']*100:.1f} ct.")
    days=sorted(r['days'].items())
    if days:
        best=max(days,key=lambda d:d[1]['counterfactual_eur']-d[1]['actual_eur']);worst=min(days,key=lambda d:d[1]['counterfactual_eur']-d[1]['actual_eur'])
        name=lambda d:WEEKDAYS[datetime.fromisoformat(d).weekday()]+' '+d[8:10]+'.'+d[5:7]+'.'
        lines.append('Kassen-Ersparnis je Tag: '+'; '.join(f"{name(d)} {v['counterfactual_eur']-v['actual_eur']:+.2f} €" for d,v in days)
                     +f". Bester Tag {name(best[0])}, schwächster {name(worst[0])} Tage mit negativer Kasse sind normal, wenn Energie für teurere Folgetage aufgehoben oder geladen wurde.")
    if devices:
        top=sorted(((v,n) for n,v in devices.items() if v>=.3),reverse=True)[:6]
        if top:lines.append('Größte Verbraucher der Woche (Energie-Dashboard, Geräte können sich überschneiden): '+', '.join(
            f"{'CEE/Tesla (nicht im Hausverbrauch)' if n=='CEE' else 'City El (nicht im Hausverbrauch)' if n=='City El' else n} {v:.1f} kWh" for v,n in top)+'.')
    metrics=(audit or {}).get('metrics',{})
    parts=[f"{label} MAE {metrics[k]['mae_kwh']:.2f} kWh aus {metrics[k]['count']} Zielen" for k,label in (('load_hour','Verbrauch je Stunde'),('pv_day','PV je Tag')) if k in metrics]
    if parts:lines.append('Prognosegüte bisher (Archiv): '+'; '.join(parts)+'.')
    if history:
        total=sum(h['cash_saving_eur'] for h in history);incl=sum(h['saving_incl_inventory_eur'] for h in history)
        lines.append(f"Seit Beginn der Messung ({len(history)} Wochen): Kasse {total:+.2f} €, inkl. Akkustand der jeweiligen Wochen {incl:+.2f} €.")
    if not calibration.get('valid'):lines.append('Hinweis: Preise teilweise nur aus dem Tibber-Archiv, Börsen-Rekonstruktion nicht verfügbar.')
    lines.append('Methode: gleiche gemessene Last, PV und Preise für beide Seiten; Stundenwerte; im Akku-voll-Fall abgeregelte PV fehlt in der Messung (begünstigt leicht die Rechnung ohne Steuerung).')
    return '\n'.join(lines)


async def run(args):
    config=load_config(BASE);ENERGY=energy_map();EVS=vehicle_entities()
    end=datetime.combine(datetime.now(TZ).date(),datetime.min.time(),TZ) if not args.end else datetime.fromisoformat(args.end).astimezone(TZ)
    start=datetime.combine((end-timedelta(days=args.days)).date(),datetime.min.time(),TZ)
    try:spot_prices.refresh(BASE/'state/training/spot_prices.json',datetime.now(TZ).date(),zone=settings.current().data['prices'].get('bidding_zone') or 'DE-LU')
    except Exception:pass
    prices,calibration=hourly_prices(BASE/'state/multiday_audit.sqlite',BASE/'state/training/spot_prices.json',end)
    energy,vehicles,battery,devices=await fetch(start,end)
    data=normalize_statistics(energy);cars=normalize_statistics(vehicles)
    ev=vehicle_energy(cars.get(EVS[0],{}),{e:cars.get(e,{}) for e in EVS[1:]}) if EVS else {}
    hours=[]
    t=start.timestamp()
    while t<end.timestamp():
        row={'start':t,'ev':ev.get(t) if EVS else 0.}
        for key,entity in ENERGY.items():row[key]=data.get(entity,{}).get(t)
        hours.append(row);t+=3600
    try:hours,start=trailing_complete(hours,prices,start)
    except WeeklyError as exc:
        span=(datetime.fromtimestamp(min(prices),TZ).strftime('%d.%m. %H:%M')+' bis '+datetime.fromtimestamp(max(prices),TZ).strftime('%d.%m. %H:%M')) if prices else 'keine'
        raise WeeklyError('%s; Preisstunden vorhanden: %d (%s), Kalibrierung gültig: %s'%(exc,len(prices),span,bool(calibration.get('valid'))))
    start_kwh=battery_at(battery,start.timestamp()-3600) or battery_at(battery,start.timestamp())
    end_kwh=battery_at(battery,end.timestamp()-3600)
    if start_kwh is None or end_kwh is None:raise ValueError('Battery energy at week boundaries unavailable')
    capacity=float(config['capacity_kwh'])
    snapshot=json.loads((BASE/'state/snapshot.json').read_text()) if (BASE/'state/snapshot.json').exists() else {}
    cal=snapshot.get('battery_calibration') or {}
    measured=config.get('efficiency_source')=='measured' and cal.get('valid')
    discharge=cal['discharge_efficiency'] if measured else config['discharge_efficiency']
    charge=cal['charge_efficiency'] if measured else config['roundtrip_efficiency']/config['discharge_efficiency']
    params=Params(capacity_kwh=capacity,reserve_kwh=capacity*config['reserve_fraction'],initial_kwh=min(capacity,max(0.,start_kwh)),
                  pv_coupling='dc',max_charge_kw=config['max_charge_kw'],max_discharge_kw=config['max_discharge_kw'],
                  discharge_efficiency=discharge,charge_efficiency=charge,grid_charge_limit_kwh=capacity*config['grid_charge_max_soc_fraction'])
    result=savings.balance(hours,prices,start_kwh,min(capacity,end_kwh),params,tail_end_value({**config,'discharge_efficiency':discharge}) or .1735*discharge)
    result.update(period_start=start.isoformat(),period_end=end.isoformat(),created_at=datetime.now(TZ).isoformat())
    weekly=BASE/'state/weekly';weekly.mkdir(parents=True,exist_ok=True)
    (weekly/f"{start.date().isoformat()}.json").write_text(json.dumps(result,indent=2))
    history=[json.loads(p.read_text()) for p in sorted(weekly.glob('*.json'))]
    history=[h for h in history if (datetime.fromisoformat(h['period_end'])-datetime.fromisoformat(h['period_start'])).days==7]
    audit=audit_summary(BASE/'state/forecast_audit.sqlite') if (BASE/'state/forecast_audit.sqlite').exists() else None
    print(facts(result,(start,end),devices,calibration,audit,history))


def main():
    p=argparse.ArgumentParser();p.add_argument('--days',type=int,default=7);p.add_argument('--end',help='ISO end (local midnight), default today 00:00')
    args=p.parse_args()
    try:asyncio.run(run(args));return 0
    except Exception as exc:
        where=''
        tb=exc.__traceback__
        while tb.tb_next:tb=tb.tb_next
        where=', '+Path(tb.tb_frame.f_code.co_filename).name+':'+str(tb.tb_lineno)   # location only: messages may carry private values
        print('[CRON_FAILURE] Wochenbilanz fehlgeschlagen ('+type(exc).__name__+where+(': '+str(exc) if isinstance(exc,WeeklyError) else '')+'). Der Akku-Betrieb ist davon nicht betroffen.',file=sys.stderr)
        return 1
if __name__=='__main__':sys.exit(main())
