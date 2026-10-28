"""Vehicle charging window (stdlib only). Recommendation only: HA cannot
control the car (no Fleet API) and this module never switches the socket. The result is
written to the user's display helper schedule.car_charge_window; charging is started by hand.

Everything is measured: charging power from hourly CEE energy, AC energy per SoC percent
from past sessions (CEE kWh vs. SoC change). The window avoids the home battery's
'serve' intervals because the WR would then feed the car from the battery (up to its
2 kW limit) instead of the expensive house hours.
Measured 25.10.2026: 0.738 kWh grid energy per 1 % SoC (8 sessions, 0.70-0.76), ~3.5 kW.
"""
import math
from datetime import datetime,timedelta
from statistics import median
from forecast import TZ
from optimizer import _ambiguous

DAYS=('monday','tuesday','wednesday','thursday','friday','saturday','sunday')


def charging_power_kw(cee_hours,minimum_kwh=2.5,minimum_samples=3):
    """Median of full charging hours (kWh per hour equals kW); None without enough samples."""
    full=[v for v in cee_hours.values() if v>=minimum_kwh]
    return median(full) if len(full)>=minimum_samples else None


def kwh_per_percent(cee_hours,soc_hours,minimum_sessions=3,minimum_kwh=3.,minimum_percent=2.):
    """Median grid kWh per SoC percent over sessions of consecutive charging hours.
    SoC is taken one or two hours before the first and after the last charging hour."""
    ratios=[];session=[]
    def close():
        if not session:return
        kwh=sum(cee_hours[t] for t in session)
        before=[soc_hours[t] for t in (session[0]-3600,session[0]-7200) if t in soc_hours]
        after=[soc_hours[t] for t in (session[-1]+3600,session[-1]+7200) if t in soc_hours]
        if before and after and kwh>=minimum_kwh and after[-1]-before[0]>=minimum_percent:
            ratios.append(kwh/(after[-1]-before[0]))
    for t in sorted(cee_hours):
        if cee_hours[t]>.2:
            if session and t-session[-1]>3600:close();session=[]
            session.append(t)
    close()
    return (median(ratios),len(ratios)) if len(ratios)>=minimum_sessions else (None,len(ratios))


def _contiguous(a,b):
    return abs(datetime.fromisoformat(a['end']).timestamp()-datetime.fromisoformat(b['start']).timestamp())<1


def plan_window(intervals,need_kwh,power_kw,margin=.1):
    """Cheapest contiguous block of non-'serve' intervals that delivers need_kwh (+margin).
    Ties go to the earliest start. Also returns the surrounding equally cheap span."""
    if need_kwh<=0:return {'status':'full'}
    if not power_kw or power_kw<=0:return {'status':'no_power'}
    need=need_kwh*(1+margin)
    ok=[f['mode']!='serve' and not _ambiguous(datetime.fromisoformat(f['start']).astimezone(TZ)) for f in intervals]
    best=None
    for i in range(len(intervals)):
        if not ok[i]:continue
        delivered=cost=0.;j=i
        while j<len(intervals) and ok[j] and (j==i or _contiguous(intervals[j-1],intervals[j])):
            take=min(power_kw*intervals[j]['duration_hours'],need-delivered)
            delivered+=take;cost+=take*intervals[j]['price_eur_kwh']
            if delivered>=need-1e-9:
                key=(round(cost,6),intervals[i]['start'])
                if best is None or key<best[0]:best=(key,i,j,cost)
                break
            j+=1
    if best is None:return {'status':'no_block'}
    _,i,j,cost=best
    block=intervals[i:j+1]
    price_cap=max(f['price_eur_kwh'] for f in block)+.003
    lo,hi=i,j
    while lo>0 and ok[lo-1] and _contiguous(intervals[lo-1],intervals[lo]) and intervals[lo-1]['price_eur_kwh']<=price_cap:lo-=1
    while hi+1<len(intervals) and ok[hi+1] and _contiguous(intervals[hi],intervals[hi+1]) and intervals[hi+1]['price_eur_kwh']<=price_cap:hi+=1
    delivered=need_kwh
    return {'status':'ok','start':block[0]['start'],'end':block[-1]['end'],'cost_eur':cost/(1+margin),
            'mean_price_eur_kwh':cost/need,'energy_kwh':delivered,'duration_h':need_kwh/power_kw,
            'flex_start':intervals[lo]['start'],'flex_end':intervals[hi]['end'],
            'blocks':[(f['start'],f['end']) for f in block]}


def week_payload(blocks):
    """Seven explicit weekdays with from/to (HH:MM, '24:00' at midnight); adjacent blocks merged."""
    week={d:[] for d in DAYS}
    for start,end in blocks:
        a=datetime.fromisoformat(start).astimezone(TZ);b=datetime.fromisoformat(end).astimezone(TZ)
        end_text='24:00' if b.hour==0 and b.minute==0 and b.date()>a.date() else b.strftime('%H:%M')
        windows=week[DAYS[a.weekday()]]
        if windows and windows[-1]['to']==a.strftime('%H:%M'):windows[-1]['to']=end_text
        else:windows.append({'from':a.strftime('%H:%M'),'to':end_text})
    return week


def evaluate(intervals,tesla,config):
    """Plan result for the report and the helper. tesla comes from the collector snapshot."""
    if not tesla or tesla.get('soc') is None or tesla.get('target_soc') is None:
        return {'status':'unknown_soc','reason':(tesla or {}).get('warning') or 'Fahrzeug-Ladestand nicht verfügbar'}
    soc,target=float(tesla['soc']),float(tesla['target_soc'])
    per_percent=tesla.get('kwh_per_percent');per_source='gemessen'
    if per_percent is None:per_percent=float(config.get('ev_kwh_per_soc_percent',.74));per_source='Config-Wert'
    power=tesla.get('power_kw');power_source='gemessen'
    if power is None:power=float(config.get('ev_power_kw',3.5));power_source='Config-Wert'
    need=max(0.,target-soc)*per_percent
    result=plan_window(intervals,need,power,float(config.get('ev_window_margin',.1)))
    result.update(soc=soc,target_soc=target,need_kwh=need,power_kw=power,kwh_per_percent=per_percent,
                  per_percent_source=per_source,power_source=power_source,plugged=tesla.get('plugged'))
    if result['status']=='ok':result['week']=week_payload(result['blocks'])
    elif result['status']=='full':result['week']=week_payload([])
    return result
