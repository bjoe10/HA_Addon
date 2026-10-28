"""Read-only, resumable year-to-date HA training collection.

Only ha_get_history and ha_get_state are called. No publishing or control imports.
Long-term statistics are not substituted for unavailable raw forecast issuances.
"""
import asyncio
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from ha_client import connection
import paths, settings
from collector import vehicle_energy

TZ = ZoneInfo('Europe/Berlin')
BASE = paths.STATE / 'training'
ENERGY = {};EV = None;EXTRA_VEHICLES = ();FORECAST = None
# No controls need to be off for read-only collection; kept as a hook for stricter setups.
SAFETY = []

def bind(cfg=None):
    """Point the module constants at the configured entities (called on import and per collection)."""
    global ENERGY,EV,EXTRA_VEHICLES,FORECAST
    cfg = cfg or settings.current()
    ENERGY = {k:cfg.entity(r,required=False) for k,r in
              (('grid','grid_import'),('wr','inverter_energy'),('charger','charger_energy'),('export','grid_export'),('pv','pv_energy'))}
    evs = cfg.entities('ev_energy')
    EV = evs[0] if evs else None
    EXTRA_VEHICLES = tuple(evs[1:])
    FORECAST = cfg.entity('pv_forecast_tomorrow',required=False)

bind()


def body(d):
    return d.get('data', d)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False))
    tmp.replace(path)


def month_chunks(start, cutoff):
    result = []
    while start < cutoff:
        end = start.replace(year=start.year+1,month=1,day=1) if start.month == 12 else start.replace(month=start.month+1,day=1)
        end = min(end, cutoff)
        result.append((start,end))
        start = end
    return result


def training_start(cutoff):
    # Do not erase model evaluation and pending prior-year forecasts on Jan 1.
    return min(cutoff.replace(month=1,day=1),cutoff-timedelta(days=90))


def expected_hours(start, end):
    return int((end.timestamp()-start.timestamp())/3600)


async def fetch_cached(ha, root, kind, args, start, end, refresh=False):
    """One request at a time; recursively subdivide any truncated responses."""
    query = dict(args, start_time=start.isoformat(), end_time=end.isoformat(),limit=1000)
    key = hashlib.sha256(json.dumps(query,sort_keys=True).encode()).hexdigest()[:16]
    path = root / 'raw' / f'{kind}_{start.date()}_{key}.json'
    if path.exists() and not refresh:
        raw = json.loads(path.read_text())
    else:
        raw = await ha.call('ha_get_history', **query)
        # Save successful incomplete queries too, but never admit them as training data.
        save(path,raw)
    b = body(raw)
    if b.get('has_more') or any(e.get('has_more') for e in b.get('entities',[])):
        if end.timestamp()-start.timestamp() <= 1:
            raise ValueError('Cannot subdivide truncated history further')
        middle = datetime.fromtimestamp((start.timestamp()+end.timestamp())/2,TZ)
        return (await fetch_cached(ha,root,kind,args,start,middle,refresh) +
                await fetch_cached(ha,root,kind,args,middle,end,refresh))
    if 'entities' not in b:
        raise ValueError('History response lacks entities')
    manifest = root / 'manifest.json'
    m = json.loads(manifest.read_text()) if manifest.exists() else {'schema_version':1,'batches':{}}
    m['batches'][path.name] = {'kind':kind,'start':start.isoformat(),'end':end.isoformat(),
                             'source':args['source'],'entity_ids':args['entity_ids'],'complete':True}
    save(manifest,m)
    return [raw]


def kwh(value, unit, power=False, negative_tolerance=0.):
    v = float(value)
    if not math.isfinite(v):
        return None
    if unit not in (('W','kW') if power else ('Wh','kWh')):
        raise ValueError('Unsupported recorded unit: '+str(unit))
    v /= 1000 if unit in ('Wh','W') else 1
    if not power and -negative_tolerance<=v<0:return 0.
    return v if v >= 0 else None


def build_dataset(stat_batches, forecast_batches, start, cutoff, forecast_unit):
    values = {e:{} for e in [*ENERGY.values(),*([EV] if EV else []),*EXTRA_VEHICLES]}
    units = {e:set() for e in values}
    duplicates = 0
    rejected = 0
    rejected_by_entity = {}
    clamped=0;clamped_kwh={}
    seen = {}
    for batch in stat_batches:
        for e in body(batch).get('entities',[]):
            entity = e['entity_id']
            if entity not in values:
                continue
            if e.get('has_more'):
                raise ValueError('Unresolved truncation')
            unit = e.get('unit_of_measurement')
            units[entity].add(str(unit))
            for r in e.get('statistics',[]):
                field = 'change'
                t = float(r['start'])/1000
                if not start.timestamp() <= t or t+3600 > cutoff.timestamp():
                    continue
                if t % 3600 != 0:
                    raise ValueError('Statistics timestamp not hour aligned')
                if r.get(field) is None:
                    continue
                v = kwh(r[field], unit, negative_tolerance=.02)
                if v==0 and float(r[field])<0:
                    clamped+=1;clamped_kwh[entity]=clamped_kwh.get(entity,0.)+abs(float(r[field]))/(1000 if unit=='Wh' else 1)
                if v is None:
                    rejected += 1
                    rejected_by_entity[entity] = rejected_by_entity.get(entity,0)+1
                    continue
                key = (entity,t)
                if key in seen:
                    if seen[key] != v:
                        raise ValueError('Conflicting duplicate statistics')
                    duplicates += 1
                    continue
                seen[key] = v
                values[entity][t] = v
    stamps = sorted(set().union(*(set(v) for v in values.values())))
    # Without a vehicle meter there is nothing to subtract.
    vehicles = vehicle_energy(values[EV],{e:values[e] for e in EXTRA_VEHICLES}) if EV else {t:0. for t in stamps}
    hours = []
    invalid_load = 0
    for t in stamps:
        components = [*(values[e].get(t) for e in [ENERGY['grid'],ENERGY['wr'],ENERGY['charger'],ENERGY['export']]),vehicles.get(t)]
        load = None
        if all(v is not None for v in components):
            g,w,c,x,ev = components
            load = g+w-c-x-ev
            if load < -.15:
                invalid_load += 1
                load = None
            else:
                load = max(0.,load)
        hours.append({'start':t,'load_kwh':load,'pv_kwh':values[ENERGY['pv']].get(t)})
    forecasts = {}
    forecast_seen = {}
    forecast_duplicates = 0
    for batch in forecast_batches:
        for entity in body(batch).get('entities',[]):
            if entity.get('has_more'):
                raise ValueError('Unresolved forecast truncation')
            for r in entity.get('states',[]):
                try:
                    issued = datetime.fromisoformat(r.get('last_updated') or r['last_changed'])
                    if issued.tzinfo is None:
                        raise ValueError('Naive forecast timestamp')
                    issued = issued.astimezone(TZ)
                    unit = r.get('attributes',{}).get('unit_of_measurement',forecast_unit)
                    v = kwh(r['state'],unit)
                except (KeyError,TypeError,ValueError):
                    continue
                target = issued.date()+timedelta(days=1)
                # Midnight query-boundary snapshots never qualify as evening issuances.
                seconds = issued.hour*3600+issued.minute*60+issued.second+issued.microsecond/1e6
                if v is None or not 16*3600 <= seconds <= 20*3600+15*60:
                    continue
                if not start.date() <= target < cutoff.date():
                    continue
                stamp = issued.timestamp()
                if stamp in forecast_seen:
                    if forecast_seen[stamp] != v:
                        raise ValueError('Conflicting duplicate forecast')
                    forecast_duplicates += 1
                forecast_seen[stamp] = v
                key = target.isoformat()
                row = {'issued_at':issued.isoformat(),'target_date':key,'predicted_kwh':v}
                if key not in forecasts or stamp > datetime.fromisoformat(forecasts[key]['issued_at']).timestamp():
                    forecasts[key] = row
    def span(ts):
        return {'first':datetime.fromtimestamp(min(ts),TZ).isoformat() if ts else None,
                'last':datetime.fromtimestamp(max(ts),TZ).isoformat() if ts else None,'hours':len(ts)}
    load_stamps = {r['start'] for r in hours if r['load_kwh'] is not None}
    pv_stamps = {r['start'] for r in hours if r['pv_kwh'] is not None}
    complete = {'load':[],'pv':[],'paired':[]}
    day = start
    while day < cutoff:
        following = day+timedelta(days=1)
        required = set(range(int(day.timestamp()),int(following.timestamp()),3600))
        if required <= load_stamps: complete['load'].append(day.date().isoformat())
        if required <= pv_stamps:
            complete['pv'].append(day.date().isoformat())
            if day.date().isoformat() in forecasts: complete['paired'].append(day.date().isoformat())
        day = following
    coverage = {'expected_hours':expected_hours(start,cutoff),'union_hours':len(hours),
                'load_hours':len(load_stamps),'pv_hours':len(pv_stamps),
                'joint_hours':len(load_stamps & pv_stamps),
                'load_complete_days':len(complete['load']),'pv_complete_days':len(complete['pv']),
                'forecast_days':len(forecasts),'pv_forecast_complete_pairs':len(complete['paired']),
                'complete_days':complete,'load_span':span(load_stamps),'pv_span':span(pv_stamps),
                'components':{e:{**span(v),'units':sorted(units[e])} for e,v in values.items()},
                'exact_duplicate_statistics':duplicates,'exact_duplicate_forecasts':forecast_duplicates,
                'rejected_negative_or_nonfinite_statistics':rejected,'rejected_negative_load_hours':invalid_load,
                'rejected_statistics_by_entity':rejected_by_entity,
                'clamped_negative_statistics':clamped,'clamped_negative_kwh_by_entity':clamped_kwh,
                'caveats':['Missing components remain null; never zero-filled.',
                           'Observed negative energy changes within 0.02 kWh per hour are clipped as inference/rounding noise, matching the operational collector; larger negative changes remain missing. Counts and clipped magnitudes are recorded.',
                           'Load = grid + WR - charger - export - EV; PV is not added.',
                           'EV is measured CEE AC energy (sensor.cee_energy, Tesla) plus City El (sensor.second_ev_energy), both user-confirmed vehicle charging; no vehicle-power proxy or powercalc estimate.',
                           'RAW_PV is an inferred DC signal, not an independent PV meter.',
                           'Forecasts are real raw evening states only (16:00–20:15); no statistical reconstruction.',
                           'Raw forecast retention may be shorter than long-term energy statistics.',
                           'Small negative load balances down to -0.15 kWh are clamped to zero (meter timing tolerance).']}
    return {'schema_version':1,'collected_at':datetime.now(TZ).isoformat(),
            'requested_start':start.isoformat(),'cutoff':cutoff.isoformat(),
            'hours':hours,'pv_forecasts':[forecasts[k] for k in sorted(forecasts)],'coverage':coverage}


def retain_issued_forecasts(dataset,previous):
    """Keep genuine previously captured issuances after HA raw-history purge.
    This never reconstructs a forecast from later actuals or aggregate means.
    """
    import copy
    result=copy.deepcopy(dataset);seen={};by_day={}
    first=datetime.fromisoformat(dataset['requested_start']).date()
    cutoff=datetime.fromisoformat(dataset['cutoff']).date()
    current_days={r.get('target_date') for r in dataset.get('pv_forecasts',[])}
    for row in [*previous.get('pv_forecasts',[]),*dataset.get('pv_forecasts',[])]:
        try:
            issued=datetime.fromisoformat(row['issued_at'])
            if issued.tzinfo is None:continue
            issued=issued.astimezone(TZ)
            target=datetime.fromisoformat(row['target_date']).date()
            value=kwh(row['predicted_kwh'],'kWh')
        except (KeyError,ValueError,TypeError):continue
        seconds=issued.hour*3600+issued.minute*60+issued.second+issued.microsecond/1e6
        if value is None or not first<=target<cutoff or issued.date()!=target-timedelta(days=1) or not 16*3600<=seconds<=20*3600+15*60:continue
        key=(row['target_date'],issued.timestamp())
        if key in seen and seen[key]!=value:raise ValueError('Conflicting immutable forecast vintage')
        seen[key]=value
        if row['target_date'] not in by_day or issued.timestamp()>datetime.fromisoformat(by_day[row['target_date']]['issued_at']).timestamp():
            by_day[row['target_date']]={'issued_at':issued.isoformat(),'target_date':row['target_date'],'predicted_kwh':value}
    result['pv_forecasts']=[by_day[d] for d in sorted(by_day)]
    coverage=result['coverage'];pv_days=coverage['complete_days']['pv']
    paired=sorted(d for d in by_day if d in pv_days)
    coverage['complete_days']['paired']=paired
    coverage['forecast_days']=len(by_day);coverage['pv_forecast_complete_pairs']=len(paired)
    coverage['retained_forecast_days']=sum(d not in current_days for d in by_day)
    return result


async def collect(root=BASE, now=None, require_disabled=False):
    bind()
    if not FORECAST:raise settings.NotConfigured('Nicht eingerichtet: PV-Prognose morgen (für das Lernen der Prognosegüte)')
    missing = [r for r in ('grid_import','grid_export','pv_energy','inverter_energy','charger_energy') if not settings.current().entity(r,required=False)]
    if missing:raise settings.NotConfigured('Nicht eingerichtet: '+', '.join(missing))
    now = now or datetime.now(TZ)
    cutoff = now.astimezone(TZ).replace(hour=0,minute=0,second=0,microsecond=0)
    start = training_start(cutoff)
    stats,forecasts = [],[]
    async with connection() as ha:
        before = body(await ha.call('ha_get_state',entity_id=[*SAFETY,FORECAST]))['states']
        if require_disabled and any(before.get(e,{}).get('state') != 'off' for e in SAFETY):
            raise ValueError('Required disabled controls are not both off; no writes performed')
        forecast_unit = before[FORECAST].get('attributes',{}).get('unit_of_measurement')
        if forecast_unit not in ('Wh','kWh'):
            raise ValueError('Cannot verify forecast energy unit')
        save(root/'safety_readback_before.json',before)
        for lo,hi in month_chunks(start,cutoff):
            # Frozen prior months; current-month complete days cached individually.
            # Refresh last two days to allow recorder aggregation to settle.
            intervals = [(lo,hi)]
            if lo.month == cutoff.month:
                intervals = []
                d = lo
                while d < hi:
                    intervals.append((d,min(d+timedelta(days=1),hi)))
                    d += timedelta(days=1)
            for left,right in intervals:
                refresh = right > cutoff-timedelta(days=2)
                stats += await fetch_cached(ha,root,'energy',{'source':'statistics','entity_ids':list(ENERGY.values()),'period':'hour','statistic_types':['change']},left,right,refresh)
                stats += await fetch_cached(ha,root,'ev',{'source':'statistics','entity_ids':[EV] if EV else [],'period':'hour','statistic_types':['change']},left,right,refresh) if EV else []
                stats += await fetch_cached(ha,root,'vehicles',{'source':'statistics','entity_ids':list(EXTRA_VEHICLES),'period':'hour','statistic_types':['change']},left,right,refresh) if EXTRA_VEHICLES else []
            forecasts += await fetch_cached(ha,root,'forecasts',{'source':'history','entity_ids':[FORECAST],'minimal_response':False,'significant_changes_only':False},lo,hi,lo.month==cutoff.month)
            print('Collected calendar chunk '+lo.date().isoformat()+' to '+hi.date().isoformat(),flush=True)
        after = body(await ha.call('ha_get_state',entity_id=SAFETY))['states']
        save(root/'safety_readback_after.json',after)
        if require_disabled and any(after.get(e,{}).get('state') != 'off' for e in SAFETY):
            raise ValueError('Safety readback is not off; collector performed no writes')
    dataset = build_dataset(stats,forecasts,start,cutoff,forecast_unit)
    previous_path=root/'annual_dataset.json'
    if previous_path.exists():
        dataset=retain_issued_forecasts(dataset,json.loads(previous_path.read_text()))
    dataset['coverage']['ev_source'] = [*([EV] if EV else []),*EXTRA_VEHICLES]
    dataset['coverage']['control_state_observed'] = {e:after.get(e,{}).get('state') for e in SAFETY}
    if all(before.get(e,{}).get('state')=='off' and after.get(e,{}).get('state')=='off' for e in SAFETY):
        dataset['coverage']['safety_controls_verified_off'] = SAFETY
    save(root/'annual_dataset.json',dataset)
    save(root/'coverage.json',dataset['coverage'])
    return dataset


if __name__ == '__main__':
    try:
        data = asyncio.run(collect())
        print(json.dumps({'dataset':str(BASE/'annual_dataset.json'),'coverage':data['coverage']},indent=2))
    except Exception as exc:
        # Never print exception messages/tracebacks: HTTP exceptions may expose credentials.
        print('Annual collection failed: '+type(exc).__name__,file=sys.stderr)
        sys.exit(1)
