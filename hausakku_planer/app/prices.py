"""Price providers. Whatever the source, the planner gets quarter-hour rows
{'start_time': ISO with offset, 'price': EUR/kWh gross} for [today 00:00, +2 days).

Providers (settings.prices.provider):
  tibber  HA service tibber.get_prices (already gross, quarter-hours)
  entity  a HA sensor whose attributes hold a price list (Nordpool, EPEX Spot, ...); unit is read from the sensor
  spot    day-ahead exchange price from energy-charts for a bidding zone, plus markup and VAT

Hourly prices are expanded to four identical quarter-hours (the price holds for the whole hour).
Gaps are never filled: the planner rejects them, and only known prices authorise schedules.
"""
import asyncio, math
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import settings, spot_prices

TZ=ZoneInfo('Europe/Berlin')
TIME_KEYS=('start','start_time','startsAt','starts_at','from','begin','time','datetime','date')
VALUE_KEYS=('value','price','total','price_per_kwh','price_kwh','amount')
PROVIDERS=('tibber','entity','spot')

class PriceError(RuntimeError):
    """A readable problem with the configured price source."""

def unit_factor(unit):
    """(factor to EUR/kWh, recognised?). Unknown or missing units are assumed to be EUR/kWh and flagged."""
    u=(unit or '').lower().replace(' ','').replace('€','eur')
    if 'mwh' in u:return .001,True
    if ('ct' in u or 'cent' in u or u.startswith('c/')) and 'kwh' in u:return .01,True
    if 'kwh' in u and ('eur' in u or u.startswith('/')):return 1.,True
    return 1.,False

def _stamp(value):
    if isinstance(value,(int,float)):return datetime.fromtimestamp(float(value),TZ)
    d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    return d if d.tzinfo else d.replace(tzinfo=TZ)

def _number(value):
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None

def parse_attributes(attrs,attribute=None):
    """{timestamp: price} from list-of-dict attributes. Without `attribute`, every such list is used (today and tomorrow)."""
    keys=[attribute] if attribute else [k for k,v in attrs.items() if isinstance(v,list) and v and isinstance(v[0],dict)]
    points={}
    for key in keys:
        for item in attrs.get(key) or []:
            if not isinstance(item,dict):continue
            t=next((item[k] for k in TIME_KEYS if k in item),None)
            v=next((x for x in (_number(item[k]) for k in VALUE_KEYS if k in item) if x is not None),None)
            if t is None or v is None:continue
            try:d=_stamp(t)
            except (ValueError,TypeError):continue
            points.setdefault(d.timestamp(),(d,v))
    return points

def to_quarter_hours(points):
    """Normalise {ts: (datetime, price)} to quarter-hour rows. 15- and 60-minute slots are supported, mixed is fine."""
    stamps=sorted(points)
    if not stamps:raise PriceError('Keine Preise gefunden.')
    rows=[]
    for i,s in enumerate(stamps):
        if i+1<len(stamps):step=stamps[i+1]-s
        else:step=s-stamps[i-1] if i else 900
        if abs(step-900)<=1:n=1
        elif abs(step-3600)<=1:n=4
        else:raise PriceError(f'Preisraster von {step/60:.0f} Minuten wird nicht unterstützt (nur 15 oder 60 Minuten).')
        price=points[s][1]
        for k in range(n):
            rows.append({'start_time':datetime.fromtimestamp(s+900*k,TZ).isoformat(),'price':price})
    return rows

def _window(rows,daystart):
    lo,hi=daystart.timestamp(),(daystart+timedelta(days=2)).timestamp()
    return [r for r in rows if lo<=datetime.fromisoformat(r['start_time']).timestamp()<hi]

def finish(price_eur,prices_cfg):
    """Add the fixed markup (ct/kWh, net) and VAT (%) to a net price."""
    return (price_eur+float(prices_cfg.get('markup_ct') or 0)/100)*(1+float(prices_cfg.get('vat_percent') or 0)/100)

async def _tibber(ha,cfg,daystart):
    raw=await ha.call('ha_call_service',domain='tibber',service='get_prices',
          data={'start':daystart.isoformat(),'end':(daystart+timedelta(days=2)).isoformat()},return_response=True,wait=False)
    homes=raw.get('service_response',{}).get('prices',{})
    wanted=cfg.get('tibber_home')
    if wanted:
        if wanted not in homes:raise PriceError('Tibber-Zuhause "'+wanted+'" nicht gefunden. Vorhanden: '+', '.join(homes))
        rows=homes[wanted]
    elif len(homes)==1:rows=next(iter(homes.values()))
    else:raise PriceError('Mehrere Tibber-Zuhause gefunden ('+', '.join(homes)+'). Bitte eines in den Einstellungen wählen.')
    points={}
    for r in rows:
        d=_stamp(r['start_time']);p=_number(r['price'])
        if p is None:raise PriceError('Tibber-Preis nicht numerisch.')
        points.setdefault(d.timestamp(),(d,p))
    return to_quarter_hours(points),{'unit':'EUR/kWh'}

async def _entity(ha,cfg,daystart):
    entity=cfg.get('entity')
    if not entity:raise PriceError('Kein Preis-Sensor eingerichtet.')
    try:state=await ha.call('ha_get_state',entity_id=entity)
    except Exception:raise PriceError('Preis-Sensor '+entity+' nicht gefunden.')
    attrs=state.get('attributes') or {}
    points=parse_attributes(attrs,cfg.get('attribute') or None)
    if not points:
        raise PriceError('Im Sensor '+entity+' wurde keine Preisliste gefunden'+(' (Attribut "'+cfg['attribute']+'")' if cfg.get('attribute') else '')+'.')
    factor,known=unit_factor(attrs.get('unit_of_measurement'))
    points={t:(d,finish(p*factor,cfg)) for t,(d,p) in points.items()}
    return to_quarter_hours(points),{'unit':attrs.get('unit_of_measurement'),'unit_known':known}

async def _spot(ha,cfg,daystart):
    zone=cfg.get('bidding_zone') or 'DE-LU'
    try:
        payload=await asyncio.to_thread(spot_prices._get,{'bzn':zone,'start':daystart.date().isoformat(),
                                                           'end':(daystart.date()+timedelta(days=2)).isoformat()})
        parsed=spot_prices.parse(payload)
    except Exception as exc:
        raise PriceError('Börsenpreise für '+zone+' nicht abrufbar ('+type(exc).__name__+').')
    points={t:(datetime.fromtimestamp(t,TZ),finish(p,cfg)) for t,p in parsed.items()}
    return to_quarter_hours(points),{'unit':'EUR/kWh (Börse + Aufschlag)'}

async def fetch(ha,daystart,cfg=None):
    """Quarter-hour price rows for [daystart, daystart+2d) and info about the source. Raises PriceError."""
    cfg=cfg or settings.current().data['prices']
    provider=cfg.get('provider','tibber')
    if provider not in PROVIDERS:raise PriceError('Unbekannter Preisanbieter: '+str(provider))
    rows,info=await {'tibber':_tibber,'entity':_entity,'spot':_spot}[provider](ha,cfg,daystart)
    rows=_window(rows,daystart)
    if not rows:raise PriceError('Für heute und morgen liegen keine Preise vor.')
    info['provider']=provider
    return rows,info

def summarize(rows,info,now=None):
    """Short facts for the UI check."""
    now=now or datetime.now(TZ)
    starts=[datetime.fromisoformat(r['start_time']) for r in rows]
    prices=[r['price'] for r in rows]
    current=next((r['price'] for r,s in zip(rows,starts) if s<=now<s+timedelta(minutes=15)),None)
    gaps=sum(1 for a,b in zip(starts,starts[1:]) if abs((b-a).total_seconds()-900)>1)
    return {'provider':info.get('provider'),'unit':info.get('unit'),'intervals':len(rows),'from':starts[0].isoformat(),
            'to':(starts[-1]+timedelta(minutes=15)).isoformat(),'min':min(prices),'max':max(prices),'now':current,'gaps':gaps}
