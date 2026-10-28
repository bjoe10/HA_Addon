"""Read-only HA data collection. Saves raw, credential-free snapshots for audits."""
import asyncio, json, math
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import paths, settings
from ha_client import connection
from forecast import energy_kwh
from openmeteo import fetch_forecast
import battery_calibration
import ev_charging
TZ=ZoneInfo('Europe/Berlin')
BASE=paths.DATA

def energy_map(cfg=None):
    """Energy counters of the house balance, by role."""
    cfg=cfg or settings.current()
    return {'grid':cfg.entity('grid_import'),'wr':cfg.entity('inverter_energy'),'charger':cfg.entity('charger_energy'),
            'export':cfg.entity('grid_export'),'pv':cfg.entity('pv_energy')}

def vehicle_entities(cfg=None):
    """AC vehicle-charging counters that are not house load, all treated alike."""
    return (cfg or settings.current()).entities('ev_energy')

def weather_entity(cfg=None):
    return (cfg or settings.current()).entity('weather',required=False)

def required_states(cfg=None):
    cfg=cfg or settings.current()
    return [cfg.entity('battery_soc')]+([cfg.entity('battery_kwh')] if cfg.entity('battery_kwh',required=False) else [])

def state_entities(cfg=None):
    """Everything the snapshot records; only `required_states` must exist."""
    cfg=cfg or settings.current()
    roles=('battery_kwh','battery_soc','battery_voltage','pv_forecast_tomorrow','pv_forecast_today_remaining','pv_forecast_today',
           'charger_switch','inverter_switch')
    ids=[cfg.entity(r,required=False) for r in roles]
    return [e for e in ids if e]+['sun.sun','input_boolean.hausakku_planer_freigabe']

def body(d): return d.get('data',d)

def normalize_hourly_weather(response,entity=None):
    """Keep valid hourly cloud observations with their original timezone."""
    data=body(response)
    forecasts=data.get('service_response',{}).get(entity or weather_entity(),{}).get('forecast',[])
    clean=[]
    for row in forecasts if isinstance(forecasts,list) else []:
        try:
            stamp=datetime.fromisoformat(str(row['datetime']))
            cloud=float(row['cloud_coverage'])
        except (KeyError,TypeError,ValueError):
            continue
        if stamp.tzinfo is None or not math.isfinite(cloud) or not 0.<=cloud<=100.:continue
        clean.append({'datetime':stamp.isoformat(),'cloud_coverage':cloud,
                      'condition':str(row.get('condition',''))[:40]})
    return clean


def normalize_statistics(d):
    out={}
    for e in body(d)['entities']:
        if e.get('has_more'): raise ValueError('Statistics truncated; narrow query or paginate')
        unit=e.get('unit_of_measurement')
        out[e['entity_id']]={}
        for r in e.get('statistics',[]):
            v=r.get('change')
            if v is None: continue
            v=energy_kwh(v,unit)
            if v<-.02: continue
            out[e['entity_id']][float(r['start'])/1000]=max(0.,v)
    return out

def vehicle_energy(cee,extras):
    """Total vehicle charging per hour: CEE plus extra vehicle meters.
    An extra meter counts as zero before its first statistic (it did not exist yet);
    afterwards a missing hour stays missing instead of being zero-filled."""
    first={e:min(v) for e,v in extras.items() if v}
    out={}
    for t,v in cee.items():
        total=v
        for e,values in extras.items():
            if t in values:total+=values[t]
            elif e in first and t>=first[e]:total=None;break
        if total is not None:out[t]=total
    return out

def device_label(d):
    """Dashboard name, or a readable name derived from the statistic id."""
    if (d.get('name') or '').strip():return d['name'].strip()
    raw=d['stat_consumption'].split('.',1)[-1]
    for suffix in ('_energy','_summation_delivered','_consumption'):
        if raw.endswith(suffix):raw=raw[:-len(suffix)]
    return raw.replace('_',' ').capitalize()

def device_consumption(prefs,stats,now):
    """kWh per energy-dashboard device for yesterday and today so far (report context only).
    Devices may overlap (e.g. a sum plug); no unassigned remainder is derived."""
    config=body(prefs).get('config',{})
    names={d['stat_consumption']:device_label(d) for d in config.get('device_consumption',[])}
    today=now.date();result={'yesterday':{},'today':{},'today_until':now.isoformat()}
    for entity,rows in normalize_statistics(stats).items():
        for start,kwh in rows.items():
            day=datetime.fromtimestamp(start,TZ).date()
            key='today' if day==today else 'yesterday' if day==today-timedelta(days=1) else None
            if key and entity in names:result[key][names[entity]]=result[key].get(names[entity],0.)+kwh
    return result

def historical_forecasts(d):
    byday={}
    for e in body(d)['entities']:
        if e.get('has_more'): raise ValueError('Forecast history truncated')
        for r in e.get('states',[]):
            try:
                v=float(r['state']); t=datetime.fromisoformat(r.get('last_updated') or r['last_changed'])
                if t.tzinfo is None:continue
                t=t.astimezone(TZ)
                if not math.isfinite(v) or v<0: continue
            except (ValueError,KeyError,TypeError): continue
            # Only data observable by the real daily 20:15 decision is eligible.
            # A later evening update would leak information into a historical test.
            wall_seconds=t.hour*3600+t.minute*60+t.second+t.microsecond/1e6
            if not 16*3600<=wall_seconds<=20*3600+15*60: continue
            day=(t.date()+timedelta(days=1)).isoformat()
            if day not in byday or t.timestamp()>byday[day][0]: byday[day]=(t.timestamp(),v)
    return {k:v[1] for k,v in byday.items()}

def join_balances(data, mapping):
    common=set.intersection(*(set(data.get(e,{})) for e in mapping.values()))
    return [{'start':t,**{key:data[e][t] for key,e in mapping.items()}} for t in sorted(common)]

async def collect():
    now=datetime.now(TZ).replace(second=0,microsecond=0)+timedelta(minutes=1)
    daystart=now.replace(hour=0,minute=0,second=0,microsecond=0)
    start=daystart-timedelta(days=28)
    end=daystart
    cfg=settings.current()
    missing=cfg.missing('plan')
    if missing:raise settings.NotConfigured('Nicht eingerichtet: '+', '.join(settings.ROLES[r][0] for r in missing))
    ENERGY=energy_map(cfg);EVS=vehicle_entities(cfg);WEATHER=weather_entity(cfg)
    FORECAST_TOMORROW=cfg.entity('pv_forecast_tomorrow',required=False)
    async with connection() as ha:
        raw={}
        raw['states']=await ha.call('ha_get_state',entity_id=state_entities(cfg))
        got=body(raw['states'])
        if set(required_states(cfg))-set(got.get('states',{})): raise ValueError('Required HA state missing')
        raw['prices']=await ha.call('ha_call_service',domain='tibber',service='get_prices',
              data={'start':daystart.isoformat(),'end':(daystart+timedelta(days=2)).isoformat()},return_response=True,wait=False)
        raw['energy']=await ha.call('ha_get_history',source='statistics',entity_ids=list(ENERGY.values()),
              start_time=start.isoformat(),end_time=end.isoformat(),period='hour',statistic_types=['change'],limit=1000)
        raw['ev']=({'entities':[]} if not EVS else await ha.call('ha_get_history',source='statistics',entity_ids=EVS,
              start_time=start.isoformat(),end_time=end.isoformat(),period='hour',statistic_types=['change'],limit=1000))
        raw['forecast_history']=({'entities':[]} if not FORECAST_TOMORROW else await ha.call('ha_get_history',entity_ids=FORECAST_TOMORROW,
              start_time=(daystart-timedelta(days=9)).isoformat(),end_time=now.isoformat(),limit=1000,minimal_response=True))
        tesla=None
        ev_soc=cfg.entity('ev_soc',required=False)
        try:
            if ev_soc and EVS:
                ev_target=cfg.entity('ev_target_soc',required=False);ev_plug=cfg.entity('ev_plug',required=False)
                st=body(await ha.call('ha_get_state',entity_id=[e for e in (ev_soc,ev_target,ev_plug) if e]))['states']
                num=lambda e:float(st[e]['state']) if e in st and str(st[e]['state']).replace('.','',1).isdigit() else None
                tesla={'soc':num(ev_soc),'target_soc':num(ev_target) if ev_target else None,
                       'plugged':bool(ev_plug) and st.get(ev_plug,{}).get('state')=='on'}
                socs=await ha.call('ha_get_history',source='statistics',entity_ids=ev_soc,
                    start_time=start.isoformat(),end_time=now.isoformat(),period='hour',statistic_types=['mean'],limit=1000)
                soc_hours={float(r['start'])/1000:float(r['mean']) for e in body(socs)['entities'] for r in e.get('statistics',[]) if r.get('mean') is not None}
                cee=normalize_statistics(raw['ev']).get(EVS[0],{})
                per,sessions=ev_charging.kwh_per_percent(cee,soc_hours)
                tesla.update(power_kw=ev_charging.charging_power_kw(cee),kwh_per_percent=per,sessions=sessions)
        except Exception as error:
            tesla=(tesla or {})|{'warning':'Fahrzeug-Daten nicht vollständig ('+type(error).__name__+')'}
        calibration=None
        try:
            # Efficiency measurement needs BMS counters; without them the configured efficiency stays.
            cal_roles={'battery_in':cfg.entity('battery_in_energy',required=False),'battery_out':cfg.entity('battery_out_energy',required=False)}
            voltage_entity=cfg.entity('battery_voltage',required=False)
            if not all(cal_roles.values()) or not voltage_entity:
                calibration={'valid':False,'reason':'Akku-Zähler für die Wirkungsgrad-Messung nicht eingerichtet'}
            else:
                cal_map={'charger':ENERGY['charger'],'wr':ENERGY['wr'],'pv':ENERGY['pv'],**cal_roles}
                # 40 days of hourly counters (<1000 rows per entity).
                counters=await ha.call('ha_get_history',source='statistics',entity_ids=list(cal_map.values()),
                    start_time=(daystart-timedelta(days=40)).isoformat(),end_time=now.isoformat(),period='hour',statistic_types=['change'],limit=1000)
                volts=await ha.call('ha_get_history',source='statistics',entity_ids=voltage_entity,
                    start_time=(daystart-timedelta(days=40)).isoformat(),end_time=now.isoformat(),period='hour',statistic_types=['mean'],limit=1000)
                normalized=normalize_statistics(counters)
                voltage={float(r['start'])/1000:float(r['mean']) for e in body(volts)['entities'] for r in e.get('statistics',[]) if r.get('mean') is not None}
                calibration=battery_calibration.calibrate({k:normalized.get(e,{}) for k,e in cal_map.items()},voltage)
        except Exception as error:
            calibration={'valid':False,'reason':'Abruf fehlgeschlagen ('+type(error).__name__+')'}
        devices=None;devices_warning=None
        try:
            prefs=await ha.call('ha_manage_energy_prefs',mode='get')
            entities=[d['stat_consumption'] for d in body(prefs).get('config',{}).get('device_consumption',[])]
            if entities:
                stats=await ha.call('ha_get_history',source='statistics',entity_ids=entities,
                    start_time=(daystart-timedelta(days=1)).isoformat(),end_time=now.isoformat(),period='hour',statistic_types=['change'],limit=100)
                devices=device_consumption(prefs,stats,now)
        except Exception as error:
            devices_warning='Device consumption unavailable ('+type(error).__name__+')'
        try:
            if not WEATHER:raise LookupError('NotConfigured')
            raw['weather']=await ha.call('ha_call_service',domain='weather',service='get_forecasts',
                entity_id=WEATHER,data={'type':'hourly'},return_response=True,wait=False)
        except Exception as error:
            raw['weather']={'service_response':{},'collection_error':type(error).__name__}
    # Optional external radiation forecast; failure only removes this PV source.
    radiation=None;radiation_warning=None
    try:
        location=cfg.location()
        if location:
            radiation=await asyncio.to_thread(fetch_forecast,*location)
        else:radiation_warning='Open-Meteo not configured'
    except Exception as error:
        radiation_warning='Open-Meteo forecast unavailable ('+type(error).__name__+')'
    data=normalize_statistics(raw['energy'])
    # Subtract actual AC car-charging energy, not vehicle-side power or DC energy.
    vehicles=normalize_statistics(raw['ev'])
    ev=vehicle_energy(vehicles.get(EVS[0],{}),{e:vehicles.get(e,{}) for e in EVS[1:]}) if EVS else {t:0. for t in data[ENERGY['grid']]}
    data['ev']=ev
    balances=join_balances(data,{**{k:v for k,v in ENERGY.items() if k!='pv'},'ev':'ev'})
    # Only full historical days are admitted, with all hourly energy rows (DST-aware).
    pvdays={}; pvshape=[[] for _ in range(24)]
    for dayoffset in range(28):
        d=start+timedelta(days=dayoffset)
        stamps=[]; t=d.timestamp(); finish=(d+timedelta(days=1)).timestamp()
        while t<finish:
            stamps.append(t);t+=3600
        if all(t in data[ENERGY['pv']] for t in stamps):
            pvdays[d.date().isoformat()]=sum(data[ENERGY['pv']][t] for t in stamps)
            for t in stamps:
                dt=datetime.fromtimestamp(t,TZ)
                pvshape[dt.hour].append(data[ENERGY['pv']][t])
    states=body(raw['states'])['states']
    prices=raw['prices'].get('service_response',{}).get('prices',{})
    if len(prices)!=1: raise ValueError('Expected exactly one Tibber home, configure explicit selection')
    weather_forecasts=normalize_hourly_weather(raw.get('weather',{}))
    weather_warning=None if weather_forecasts else (
        'No valid hourly DWD cloud forecast; future PV uses historical climatology.' if not raw.get('weather',{}).get('collection_error')
        else 'DWD weather forecast unavailable; future PV uses historical climatology ('+raw['weather']['collection_error']+').')
    snapshot={'collected_at':datetime.now(TZ).isoformat(),'planning_start':now.isoformat(),
       'states':states,'prices':next(iter(prices.values())), 'balances':balances,
       'pv_actual_by_day':pvdays,'pv_shape_samples':pvshape,
       'pv_predicted_by_day':historical_forecasts(raw['forecast_history']),
       'weather_forecasts':weather_forecasts,'weather_forecast_warning':weather_warning,
       'radiation_forecast':radiation,'radiation_forecast_warning':radiation_warning,
       'device_consumption':devices,'device_consumption_warning':devices_warning,
       'battery_calibration':calibration,'ev_charging':tesla,
       'ev_hour_count':len(ev),'ev_source':EVS,'ev_method':'measured_AC_energy_change','raw':raw}
    state=BASE/'state';state.mkdir(exist_ok=True)
    (state/'snapshot.json').write_text(json.dumps(snapshot,indent=2))
    archive=state/'snapshots';archive.mkdir(exist_ok=True)
    (archive/(now.strftime('%Y-%m-%d_%H-%M')+'.json')).write_text(json.dumps(snapshot,indent=2))
    # Keep a bounded rolling archive (56 snapshots), newest first.
    for old in sorted(archive.glob('*.json'),reverse=True)[56:]: old.unlink()
    return snapshot

if __name__=='__main__':
    d=asyncio.run(collect())
    print(json.dumps({'collected_at':d['collected_at'],'prices':len(d['prices']),
       'historical_balance_hours':len(d['balances']),'pv_complete_days':len(d['pv_actual_by_day']),
       'historical_forecast_days':len(d['pv_predicted_by_day']),'ev_hour_count':d['ev_hour_count']},indent=2))
