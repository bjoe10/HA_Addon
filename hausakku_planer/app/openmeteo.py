"""Open-Meteo radiation PV forecast, calibrated on the own (shaded) PV measurements.
Coordinates are rounded town level (user-approved). No API key, stdlib only.

Open-Meteo hourly radiation is the mean of the PRECEDING hour: the value stamped
T describes T-1h..T. It is stored here under the PV hour START (T-1h).
Per target day, the 30 complete measured days with the nearest solar declination
calibrate per UTC hour pv = a*direct + b*diffuse (a,b >= 0). Shading depends on
sun position, so this captures it without panel geometry.
Backtest 2026 (short-lead historical forecasts, so optimistic for day-ahead):
daily MAE 1.12 kWh vs 2.73 seasonal climatology; October 0.74 vs 1.49 HA x ratio.
"""
import json,math
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from forecast import TZ
from multiday import _declination,_db,_stamp

UTC=timezone.utc
FORECAST_URL='https://api.open-meteo.com/v1/forecast'
HISTORY_URL='https://historical-forecast-api.open-meteo.com/v1/forecast'
FIELDS=('shortwave_radiation','direct_radiation','diffuse_radiation','cloud_cover')


def _get(url,params,timeout=30):
    with urlopen(url+'?'+urlencode(params),timeout=timeout) as response:
        return json.loads(response.read().decode())


def parse(payload):
    """{PV hour start (UTC timestamp): [ghi, direct, diffuse, cloud]}; gaps are skipped."""
    hourly=payload.get('hourly',{})
    result={}
    for i,stamp in enumerate(hourly.get('time',[])):
        try:values=[float(hourly[f][i]) for f in FIELDS]
        except (KeyError,TypeError,ValueError,IndexError):continue
        if not all(math.isfinite(v) and v>=0 for v in values):continue
        end=datetime.fromisoformat(stamp).replace(tzinfo=UTC).timestamp()
        result[end-3600]=values
    return result


def _params(lat,lon,**extra):
    return {'latitude':f'{lat:.2f}','longitude':f'{lon:.2f}','hourly':','.join(FIELDS),'timezone':'GMT',**extra}


def fetch_forecast(lat,lon,days=5):
    payload=_get(FORECAST_URL,_params(lat,lon,past_days=1,forecast_days=days))
    hours=parse(payload)
    if not hours:raise ValueError('Empty Open-Meteo forecast')
    return {'issued_at':datetime.now(TZ).isoformat(),'source':FORECAST_URL,
            'hours':{str(int(k)):v for k,v in sorted(hours.items())}}


def refresh_history(path,lat,lon,today,first=date(2026,1,1)):
    """Incremental cache of historical short-lead forecasts up to yesterday."""
    path=Path(path)
    cache=json.loads(path.read_text()) if path.exists() else {'hours':{}}
    if cache.get('latitude')!=round(lat,2) or cache.get('longitude')!=round(lon,2):cache={'hours':{}}
    hours={float(k):v for k,v in cache['hours'].items()}
    start=first
    if hours:start=max(first,datetime.fromtimestamp(max(hours),UTC).date()-timedelta(days=2))
    end=today-timedelta(days=1)
    if start<=end:
        hours.update(parse(_get(HISTORY_URL,_params(lat,lon,start_date=start.isoformat(),end_date=end.isoformat()))))
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.new')
        temp.write_text(json.dumps({'latitude':round(lat,2),'longitude':round(lon,2),
                                    'hours':{str(int(k)):v for k,v in sorted(hours.items())}}))
        temp.replace(path)
    return hours


def _day_hours(day):
    t=datetime.combine(day,datetime.min.time(),TZ).timestamp()
    stop=datetime.combine(day+timedelta(days=1),datetime.min.time(),TZ).timestamp()
    while t<stop:
        yield t;t+=3600


def training_days(dataset,history,issue):
    """Complete measured PV days before the issue date that have radiation for every hour."""
    pv={r['start']:r['pv_kwh'] for r in (dataset or {}).get('hours',[])
        if r.get('pv_kwh') is not None and math.isfinite(r['pv_kwh']) and r['pv_kwh']>=0}
    days={}
    for stamp in pv:
        day=datetime.fromtimestamp(stamp,TZ).date()
        if day<issue.date():days.setdefault(day,None)
    complete={}
    for day in days:
        stamps=list(_day_hours(day))
        if all(t in pv and t in history for t in stamps):complete[day]=[(t,pv[t],history[t]) for t in stamps]
    return complete


def fit_day(training,day,neighbours=30):
    """Per UTC hour nonnegative least squares pv = a*direct + b*diffuse."""
    if len(training)<neighbours:return None
    target=_declination(day)
    near=sorted(training,key=lambda d:(abs(_declination(d)-target),abs((day-d).days)))[:neighbours]
    sums=[[0.]*5 for _ in range(24)]
    for d in near:
        for t,pv,(ghi,direct,diffuse,cloud) in training[d]:
            s=sums[datetime.fromtimestamp(t,UTC).hour]
            s[0]+=direct*direct;s[1]+=diffuse*diffuse;s[2]+=direct*diffuse;s[3]+=direct*pv;s[4]+=diffuse*pv
    coefficients=[]
    for xx,yy,xy,xp,yp in sums:
        det=xx*yy-xy*xy
        a=b=0.
        if det>1e-9:
            a=(xp*yy-yp*xy)/det;b=(yp*xx-xp*xy)/det
        if a<0 or b<0 or det<=1e-9:
            # Best single-input fit instead of a negative coefficient.
            only_a=(xp/xx if xx>0 else 0.,0.);only_b=(0.,yp/yy if yy>0 else 0.)
            error=lambda c:c[0]*c[0]*xx+c[1]*c[1]*yy+2*c[0]*c[1]*xy-2*c[0]*xp-2*c[1]*yp
            a,b=min((only_a,only_b),key=error)
        coefficients.append((max(0.,a),max(0.,b)))
    return {'coefficients':coefficients,'matched_from':min(near).isoformat(),'matched_to':max(near).isoformat(),
            'training_days':len(near)}


def hourly_pv(dataset,history,forecast,issue,neighbours=30):
    """{PV hour start: kWh} for every forecast hour from the issue day on, or None."""
    training=training_days(dataset,history,issue)
    hours={float(k):v for k,v in forecast['hours'].items()}
    fits={};result={}
    for t,(ghi,direct,diffuse,cloud) in sorted(hours.items()):
        day=datetime.fromtimestamp(t,TZ).date()
        if day<issue.date():continue
        if day not in fits:fits[day]=fit_day(training,day,neighbours)
        if fits[day] is None:return None
        a,b=fits[day]['coefficients'][datetime.fromtimestamp(t,UTC).hour]
        result[t]=a*direct+b*diffuse
    return {'hours':result,'fits':{d.isoformat():{k:v for k,v in f.items() if k!='coefficients'} for d,f in fits.items()},
            'training_days_available':len(training)}


def load_history(path):
    path=Path(path)
    if not path.exists():return None
    return {float(k):v for k,v in json.loads(path.read_text())['hours'].items()}


def archive_radiation(path,snapshot):
    """Keep every Open-Meteo forecast vintage for honest day-ahead evaluation later."""
    forecast=snapshot.get('radiation_forecast')
    if not forecast:return 0
    issue=_stamp(snapshot['collected_at'])
    with _db(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS radiation (target REAL, issued REAL, payload TEXT, PRIMARY KEY(target,issued))')
        for target,values in forecast['hours'].items():
            db.execute('INSERT OR IGNORE INTO radiation VALUES (?,?,?)',(float(target),issue,json.dumps(values)))
    return len(forecast['hours'])


def apply_radiation(data,snapshot,dataset,history):
    """Replace known-horizon PV by the calibrated radiation model; fall back on any gap."""
    fallback={'source':'ha_solarforecast_ratio'}
    forecast=snapshot.get('radiation_forecast')
    if not forecast:return {**fallback,'warning':snapshot.get('radiation_forecast_warning') or 'no Open-Meteo forecast'}
    if not history:return {**fallback,'warning':'no Open-Meteo calibration history'}
    issue=datetime.fromisoformat(snapshot['collected_at']).astimezone(TZ)
    model=hourly_pv(dataset,history,forecast,issue)
    if model is None:return {**fallback,'warning':'too few calibration days'}
    hours=model['hours']
    needed=[math.floor(r['start'].timestamp()/3600)*3600 for r in data['intervals']]
    if any(float(h) not in hours for h in needed):return {**fallback,'warning':'Open-Meteo forecast does not cover price horizon'}
    totals={}
    for r,h in zip(data['intervals'],needed):
        r['pv_kwh']=hours[float(h)]*(r['end'].timestamp()-r['start'].timestamp())/3600
        day=r['start'].date().isoformat();totals[day]=totals.get(day,0.)+r['pv_kwh']
    data['pv_totals_corrected_kwh']=totals
    return {'source':'openmeteo_radiation','fits':model['fits'],'training_days_available':model['training_days_available'],
            'issued_at':forecast['issued_at'],'hours':{str(int(k)):v for k,v in hours.items()}}
