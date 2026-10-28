"""Forecast helpers. Historical balances, robust hourly loads, paired PV calibration.
No claim of model accuracy: a profile is a baseline, not a weather model.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from statistics import median
import math
TZ = ZoneInfo('Europe/Berlin')

def energy_kwh(value, unit):
    v=float(value)
    if not math.isfinite(v): raise ValueError('Non-finite energy')
    if unit == 'Wh': return v/1000
    if unit == 'kWh': return v
    raise ValueError('Unsupported energy unit: '+str(unit))

def estimate(samples, estimator='median', half_life_days=7.):
    """samples: [(value, age_days)]. 'median' or 'weighted_mean' (exponential recency weights).
    Backtest 25.10.2026 (12 load days): daily MAE median 1.85 / mean 1.52 / weighted mean
    (half-life 7 d) 1.43 kWh; the median systematically underestimated energy (bias -1.6 kWh)."""
    if not samples:return None
    if estimator=='median':return median(v for v,_ in samples)
    if estimator!='weighted_mean' or not half_life_days>0:raise ValueError('Unknown load estimator')
    weights=[0.5**(max(0.,a)/half_life_days) for _,a in samples]
    return sum(w*v for w,(v,_) in zip(weights,samples))/sum(weights)

def load_profile(rows, estimator='median', half_life_days=7., now=None):
    groups={'all':[[] for _ in range(24)], 'weekday':[[] for _ in range(24)], 'weekend':[[] for _ in range(24)]}
    for r in rows:
        if any(r.get(k) is None for k in ('grid','wr','charger','export','ev')):
            continue
        t=datetime.fromtimestamp(r['start'],TZ)
        # PV is DC coupled: the WR meter already includes solar AND battery output.
        # Adding RAW_PV or battery output again would double-count generation.
        val=r['grid']+r['wr']-r['charger']-r['export']-r['ev']
        if not math.isfinite(val) or val < -.15: continue
        val=max(0.,val)
        age=(now.timestamp()-r['start'])/86400 if now is not None else 0.
        groups['all'][t.hour].append((val,age))
        groups['weekend' if t.weekday()>=5 else 'weekday'][t.hour].append((val,age))
    if not any(groups['all']): raise ValueError('No complete historical load balances')
    result={key:[estimate(x,estimator,half_life_days) for x in values] for key,values in groups.items()}
    result['samples']={key:[len(x) for x in values] for key,values in groups.items()}
    return result

def pv_calibration(actual_by_day, predicted_by_day, today):
    ratios=[]
    for day in sorted(set(actual_by_day)&set(predicted_by_day)):
        a,p=actual_by_day[day],predicted_by_day[day]
        if day<today and p>=.2 and a>=0 and math.isfinite(a/p):
            ratios.append(a/p)
    # Extreme ratios are reported rather than silently clipped into false precision.
    return {'factor':median(ratios) if ratios else 1.,'pairs':len(ratios),'ratios':ratios}

def price_intervals(rows, now):
    if now.tzinfo is None: raise ValueError('Timezone-aware now required')
    points={}
    for r in rows:
        d=datetime.fromisoformat(r['start_time'])
        if d.tzinfo is None: raise ValueError('Price timestamp has no offset')
        stamp=d.timestamp()
        p=float(r['price'])
        if not math.isfinite(p): raise ValueError('Price not finite')
        if stamp in points and points[stamp][1] != p: raise ValueError('Conflicting duplicate price')
        points[stamp]=(d,p)
    stamps=sorted(points)
    if not stamps: raise ValueError('No price intervals')
    # This HA integration was verified to return quarter-hour prices. Never fill gaps.
    if any(abs(b-a-900)>1 for a,b in zip(stamps,stamps[1:])):
        raise ValueError('Price data gap or unsupported interval resolution')
    result=[]
    for stamp in stamps:
        d,p=points[stamp]
        end=datetime.fromtimestamp(stamp+900,TZ)
        if end.timestamp()<=now.timestamp(): continue
        start=datetime.fromtimestamp(max(stamp,now.timestamp()),TZ)
        result.append({'start':start,'end':end,'price_eur_kwh':p})
    if not result or result[0]['start'].timestamp()>now.timestamp()+1:
        raise ValueError('Current price interval missing')
    return result
