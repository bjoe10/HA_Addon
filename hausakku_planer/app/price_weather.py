"""Weather correction of the estimated price level (wind and sun across Germany). stdlib only.

Wind sets the German exchange price above all else, in winter almost alone; strong sun lowers
it too. Eight fixed points from the North Sea to central Germany (no household location) give
a daily wind capacity factor and mean irradiance from Open-Meteo, no API key.

The correction is a small linear regression of the shaped price model's daily-level error on
  [1, wind(day), wind(anchor)*p^k, sun(day), sun(anchor)*p^k]   per horizon k = 1..3 days,
fitted on up to 365 days of exchange prices and archived short-lead weather forecasts. It is
fitted in exchange-price space and scaled by the exact Tibber factor (Tibber = fixed + factor x
exchange, so baseline and error scale linearly). It is applied only if it also beats the plain
model on the last 60 days, fitted without them.

Backtest Sep 2024 - Nov 2026 with the forecasts really known 2-4 days ahead (hourly MAE ct):
all 3.70 -> 3.22, winter (Nov-Feb) 3.95 -> 3.12, summer 3.33 -> 3.14; temperature added nothing.
"""
import json,math
from datetime import date,datetime,timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from forecast import TZ
from multiday import shaped_from_profiles,shaped_level

FORECAST_URL='https://api.open-meteo.com/v1/forecast'
HISTORY_URL='https://historical-forecast-api.open-meteo.com/v1/forecast'
# Wind regions of the German grid: Schleswig-Holstein, Lower Saxony coast, Brandenburg, Saxony-Anhalt,
# Mecklenburg, North Sea and Baltic offshore, central Germany.
POINTS=((54.6,9.0),(53.6,7.8),(53.0,13.0),(52.0,11.5),(53.9,12.2),(54.5,6.5),(54.8,13.8),(51.5,9.5))
HISTORY_DAYS=430
TRAIN_DAYS=365
VALIDATION_DAYS=60
MIN_ROWS=60
HORIZONS=(1,2,3)


def capacity_factor(speed):
    """Rough wind turbine power curve on hub-height wind (m/s): cut-in 3, rated 12, cut-out 25."""
    if speed is None or not math.isfinite(speed) or speed<3 or speed>=25:return 0.
    return min(1.,((speed-3)/9)**3)


def _get(url,params,timeout=60):
    with urlopen(url+'?'+urlencode(params),timeout=timeout) as response:
        return json.loads(response.read().decode())


def daily_features(payload):
    """{local date: [mean wind capacity factor, mean irradiance W/m2]} over all points; incomplete days skipped."""
    locations=payload if isinstance(payload,list) else [payload]
    sums={}
    for loc in locations:
        hourly=loc.get('hourly',{})
        for stamp,wind,sun in zip(hourly.get('time',[]),hourly.get('wind_speed_100m',[]),hourly.get('shortwave_radiation',[])):
            if wind is None or sun is None:continue
            entry=sums.setdefault(stamp[:10],[0.,0.,0])
            entry[0]+=capacity_factor(float(wind));entry[1]+=float(sun);entry[2]+=1
    need=len(locations)*23
    return {d:[w/n,s/n] for d,(w,s,n) in sums.items() if n>=need}


def _params(**extra):
    return {'latitude':','.join(str(a) for a,_ in POINTS),'longitude':','.join(str(b) for _,b in POINTS),
            'hourly':'wind_speed_100m,shortwave_radiation','wind_speed_unit':'ms','timezone':'Europe/Berlin',**extra}


def load(path):
    path=Path(path)
    try:return json.loads(path.read_text()) if path.exists() else {}
    except ValueError:return {}


def save(path,state):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.new');temp.write_text(json.dumps(state,sort_keys=True));temp.replace(path)


def refresh(state,today,get=_get):
    """Archived short-lead forecasts up to yesterday (incremental, HISTORY_DAYS kept) and the current forecast."""
    history=dict(state.get('history',{}))
    first=today-timedelta(days=HISTORY_DAYS)
    start=first
    if history and min(history)<=(first+timedelta(days=2)).isoformat():
        start=max(first,date.fromisoformat(max(history))-timedelta(days=2))
    end=today-timedelta(days=1)
    if start<=end:
        history.update(daily_features(get(HISTORY_URL,_params(start_date=start.isoformat(),end_date=end.isoformat()))))
    history={d:v for d,v in history.items() if d>=first.isoformat()}
    forecast=daily_features(get(FORECAST_URL,_params(past_days=1,forecast_days=6)))
    if not forecast:raise ValueError('Empty Open-Meteo wind forecast')
    return {**state,'history':history,'forecast':{'issued_at':datetime.now(TZ).isoformat(),'days':forecast}}


def exchange_profiles(spot):
    """{local date: (daily mean, {hour: mean})} from exchange prices (EUR/kWh, hourly or quarter-hourly)."""
    hours={}
    for stamp,price in spot.items():
        t=datetime.fromtimestamp(float(stamp),TZ)
        hours.setdefault(t.date(),{}).setdefault(t.hour,[]).append(price)
    result={}
    for day,values in hours.items():
        if len(values)<23:continue
        hourly={h:sum(v)/len(v) for h,v in values.items()}
        result[day]=(sum(hourly.values())/len(hourly),hourly)
    return result


def _features(weather_target,weather_anchor,k,persistence):
    decay=persistence**k
    return [1.,weather_target[0],weather_anchor[0]*decay,weather_target[1]/100,weather_anchor[1]/100*decay]


def _solve(rows,targets,ridge=1e-3):
    n=len(rows[0])
    m=[[sum(x[i]*x[j] for x in rows)+(ridge*len(rows) if i==j and i>0 else 0.) for j in range(n)] for i in range(n)]
    b=[sum(x[i]*y for x,y in zip(rows,targets)) for i in range(n)]
    for c in range(n):
        p=max(range(c,n),key=lambda r:abs(m[r][c]))
        if abs(m[p][c])<1e-12:raise ValueError('Singular weather regression')
        m[c],m[p]=m[p],m[c];b[c],b[p]=b[p],b[c]
        for r in range(n):
            if r!=c:
                f=m[r][c]/m[c][c];m[r]=[a-f*q for a,q in zip(m[r],m[c])];b[r]-=f*b[c]
    return [b[i]/m[i][i] for i in range(n)]


def training_rows(profiles,history,today,persistence,long_days,weekday,holidays):
    """(k, target date, features, level error) of the shaped model for past anchors; causal: only complete days."""
    rows=[]
    days=sorted(profiles)
    for anchor in days:
        if not today-timedelta(days=TRAIN_DAYS+3)<=anchor<today:continue
        if anchor.isoformat() not in history:continue
        if (anchor-days[0]).days<max(long_days,56 if weekday else 28):continue   # not enough past for the baseline
        model=shaped_from_profiles(profiles,anchor,persistence,long_days,weekday,holidays)
        for k in HORIZONS:
            target=anchor+timedelta(days=k)
            if target>=today or target not in profiles or target.isoformat() not in history:continue
            error=profiles[target][0]-shaped_level(model,target)
            rows.append((k,target,_features(history[target.isoformat()],history[anchor.isoformat()],k,persistence),error))
    return rows


def fit(spot,state,today,persistence=.3,long_days=56,weekday=True,holidays=True):
    """Coefficients per horizon plus the validation verdict. Errors in exchange EUR/kWh."""
    history=state.get('history',{})
    rows=training_rows(exchange_profiles(spot),history,today,persistence,long_days,weekday,holidays)
    split=today-timedelta(days=VALIDATION_DAYS)
    result={'fitted_on':today.isoformat(),'persistence':persistence,'rows':len(rows),'active':False}
    early={k:[r for r in rows if r[0]==k and r[1]<split] for k in HORIZONS}
    late=[r for r in rows if r[1]>=split]
    if any(len(v)<MIN_ROWS for v in early.values()) or len(late)<20:
        return {**result,'reason':f'zu wenig Lerndaten ({len(rows)} Tage)'}
    try:early_coef={k:_solve([r[2] for r in v],[r[3] for r in v]) for k,v in early.items()}
    except ValueError:return {**result,'reason':'Regression nicht lösbar'}
    plain=sum(abs(r[3]) for r in late)/len(late)
    corrected=sum(abs(r[3]-sum(a*x for a,x in zip(early_coef[r[0]],r[2]))) for r in late)/len(late)
    result.update(validation_days=len({r[1] for r in late}),validation_error_plain=plain,validation_error_weather=corrected)
    if corrected>=plain:
        return {**result,'reason':'kein Vorteil in den letzten 60 Tagen'}
    coefficients={str(k):_solve([r[2] for r in rows if r[0]==k],[r[3] for r in rows if r[0]==k]) for k in HORIZONS}
    return {**result,'active':True,'coefficients':coefficients,'reason':'aktiv'}


def correction(state,model,factor):
    """callable(anchor date, day) -> Tibber EUR/kWh added to the daily level, or None if unknown."""
    days=(state.get('forecast') or {}).get('days',{})
    def apply(anchor,day):
        if not model or not model.get('active'):return None
        k=(day-anchor).days
        coef=model['coefficients'].get(str(min(max(k,1),max(HORIZONS))))
        target=days.get(day.isoformat());base=days.get(anchor.isoformat())
        if coef is None or target is None or base is None:return None
        return factor*sum(a*x for a,x in zip(coef,_features(target,base,max(k,1),model['persistence'])))
    return apply


LOG_DAYS=60


def log_forecast(path,tail,issued):
    """Keep the estimated daily level with and without weather correction per (issue day, target day).
    The first main run of a day counts; LOG_DAYS kept. Read by the weekly report."""
    path=Path(path)
    try:log=json.loads(path.read_text()) if path.exists() else []
    except ValueError:log=[]
    levels={}
    for row,plain,weather in zip(tail.get('rows',[]),tail.get('uncorrected_prices',[]),tail.get('baseline_prices',[])):
        levels.setdefault(row['start'][:10],[]).append((plain,weather))
    seen={(e['issued'],e['target']) for e in log}
    for day,values in sorted(levels.items()):
        if len(values)<23 or (issued.isoformat(),day) in seen:continue
        log.append({'issued':issued.isoformat(),'target':day,'plain':sum(p for p,_ in values)/len(values),
                    'weather':sum(w for _,w in values)/len(values)})
    cutoff=(issued-timedelta(days=LOG_DAYS)).isoformat()
    log=[e for e in log if e['target']>=cutoff]
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.new');temp.write_text(json.dumps(log));temp.replace(path)
    return log


def week_errors(log,actual,start,end):
    """Mean absolute daily-level error (EUR/kWh) without and with weather for targets in [start, end).
    actual: {date iso: real daily mean Tibber price}."""
    pairs=[(abs(e['plain']-actual[e['target']]),abs(e['weather']-actual[e['target']]))
           for e in log if start.isoformat()<=e['target']<end.isoformat() and e['target'] in actual]
    if not pairs:return None
    return {'count':len(pairs),'plain':sum(p for p,_ in pairs)/len(pairs),'weather':sum(w for _,w in pairs)/len(pairs)}
