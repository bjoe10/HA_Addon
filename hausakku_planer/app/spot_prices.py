"""Day-ahead exchange prices (energy-charts, DE-LU, CC BY 4.0 Bundesnetzagentur/SMARD)
reconstructed into Tibber prices for the tail price model. stdlib only.

Tibber = fixed + factor * exchange; fitted on every run against the archived real
Tibber vintages (24.10.2026: 0.1735 EUR/kWh + 1.19 x exchange, max error 0.01 ct
over 868 quarter-hours). Reconstruction is used only when that fit stays exact, so
a tariff change disables it instead of silently shifting prices. Reconstructed rows
are history for the tail baseline, never prospective vintages or schedule input.
"""
import json,math
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from forecast import TZ

UTC=timezone.utc
URL='https://api.energy-charts.info/price'


def _get(params,timeout=60):
    with urlopen(URL+'?'+urlencode(params),timeout=timeout) as response:
        return json.loads(response.read().decode())


def parse(payload):
    """{quarter-hour start timestamp: exchange price EUR/kWh}; gaps are skipped."""
    if payload.get('unit')!='EUR / MWh':raise ValueError('Unexpected exchange price unit')
    result={}
    for stamp,price in zip(payload.get('unix_seconds',[]),payload.get('price',[])):
        if price is None or not math.isfinite(float(price)):continue
        result[float(stamp)]=float(price)/1000
    return result


def refresh(path,today,first=date(2026,1,1),zone='DE-LU'):
    """Incremental cache up to and including tomorrow (day-ahead is known after ~13:00)."""
    path=Path(path)
    cached=json.loads(path.read_text()) if path.exists() else {}
    # A cache from another bidding zone must not be mixed in.
    prices={float(k):v for k,v in cached.get('prices',{}).items()} if cached.get('bzn','DE-LU')==zone else {}
    start=first if not prices else max(first,datetime.fromtimestamp(max(prices),TZ).date()-timedelta(days=2))
    prices.update(parse(_get({'bzn':zone,'start':start.isoformat(),'end':(today+timedelta(days=1)).isoformat()})))
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.new')
    temp.write_text(json.dumps({'source':URL,'bzn':zone,'prices':{str(int(k)):v for k,v in sorted(prices.items())}}))
    temp.replace(path)
    return prices


def load(path):
    path=Path(path)
    return {float(k):v for k,v in json.loads(path.read_text())['prices'].items()} if path.exists() else None


def calibrate(spot,archive,max_error=.001,minimum=96):
    """Least-squares Tibber = fixed + factor * exchange on overlapping quarter-hours."""
    pairs=[(spot[r['start']],r['price']) for r in archive if r['start'] in spot]
    if len(pairs)<minimum:return {'valid':False,'pairs':len(pairs),'reason':'too few overlapping Tibber prices'}
    mx=sum(x for x,_ in pairs)/len(pairs);my=sum(y for _,y in pairs)/len(pairs)
    var=sum((x-mx)**2 for x,_ in pairs)
    if var<=0:return {'valid':False,'pairs':len(pairs),'reason':'no exchange price variation'}
    factor=sum((x-mx)*(y-my) for x,y in pairs)/var;fixed=my-factor*mx
    error=max(abs(y-fixed-factor*x) for x,y in pairs)
    return {'valid':error<=max_error,'pairs':len(pairs),'fixed_eur_kwh':fixed,'factor':factor,'max_error_eur_kwh':error,
            'reason':'exact tariff fit' if error<=max_error else 'tariff fit not exact; reconstruction disabled'}


def reconstructed_history(spot,calibration,archive):
    """Tibber-equivalent rows for quarter-hours missing in the real archive.
    issued_at is noon of the previous local day (day-ahead auction), so the
    causal filters treat them like prices known one day ahead.
    """
    if not calibration.get('valid'):return []
    known={r['start'] for r in archive}
    rows=[]
    for stamp,price in sorted(spot.items()):
        if stamp in known:continue
        day=datetime.fromtimestamp(stamp,TZ).date()
        issued=datetime.combine(day-timedelta(days=1),datetime.min.time(),TZ).replace(hour=12).timestamp()
        rows.append({'start':stamp,'issued_at':issued,'price':calibration['fixed_eur_kwh']+calibration['factor']*price,
                     'reconstructed':True})
    return rows
