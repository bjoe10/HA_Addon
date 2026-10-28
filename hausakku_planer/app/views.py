"""Pure functions behind the web UI: plan view, entity suggestions, settings validation."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import settings

TZ=ZoneInfo('Europe/Berlin')
MODE_LABEL={'charge':'Laden','serve':'Versorgen','hold':'Halten'}

def _t(value):
    return datetime.fromisoformat(value)

def _ct(price):
    return f'{price*100:.1f}'.replace('.',',')+' ct'

def _kwh(value):
    return f'{value:.1f}'.replace('.',',')+' kWh'

def explain(mode,avg_price,kwh,horizon_avg):
    """One German sentence for a window, from numbers only."""
    diff=avg_price-horizon_avg
    rel=f'{abs(diff)*100:.1f}'.replace('.',',')+' ct '+('unter' if diff<0 else 'über')+' dem Durchschnitt'
    if mode=='charge':
        return f'Netzladen: {_kwh(kwh)} bei Ø {_ct(avg_price)}, {rel}. Die geladene Energie ersetzt später teureren Netzbezug.'
    if mode=='serve':
        return f'Der Akku versorgt das Haus ({_kwh(kwh)} statt Netzbezug) bei Ø {_ct(avg_price)}, {rel}.'
    return f'Akku wird geschont (Ø {_ct(avg_price)}, {rel}); PV lädt weiter. Die Energie bleibt für teurere Stunden.'

def windows(intervals):
    """Consecutive intervals with the same mode, merged, with time-weighted average price."""
    out=[]
    for iv in intervals:
        hours=(_t(iv['end'])-_t(iv['start'])).total_seconds()/3600
        if out and out[-1]['mode']==iv['mode']:
            w=out[-1]
        else:
            w={'mode':iv['mode'],'start':iv['start'],'hours':0.,'price_hours':0.,'charge_kwh':0.,'serve_kwh':0.}
            out.append(w)
        w['end']=iv['end'];w['hours']+=hours;w['price_hours']+=iv['price']*hours
        w['charge_kwh']+=iv['charge_kwh'];w['serve_kwh']+=iv['serve_kwh'];w['end_soc_kwh']=iv['soc_kwh']
    return out

PV_WARNINGS={'no Open-Meteo forecast':'Keine Open-Meteo-Strahlungsprognose; die PV-Schätzung stützt sich auf die Prognose in Home Assistant. Mit Standort in den Einstellungen wird sie genauer.'}

def plan_view(plan,now=None):
    """Condensed plan for the UI. `plan` is the planner's plan.json content."""
    now=now or datetime.now(TZ)
    p=plan['plan'];inputs=plan['inputs'];policy=plan.get('operating_policy') or {}
    intervals=[{'start':i['start'],'end':i['end'],'mode':i['mode'],'price':i['price_eur_kwh'],'load_kwh':i['load_kwh'],'pv_kwh':i['pv_kwh'],
                'soc_kwh':i['terminal_kwh'],'charge_kwh':i['charger_ac_kwh'],'serve_kwh':i['served_ac_kwh']} for i in p['intervals']]
    total_hours=sum((_t(i['end'])-_t(i['start'])).total_seconds()/3600 for i in intervals) or 1.
    horizon_avg=sum(i['price']*(_t(i['end'])-_t(i['start'])).total_seconds()/3600 for i in intervals)/total_hours
    wins=[]
    for w in windows(intervals):
        avg=w['price_hours']/w['hours']
        kwh=w['charge_kwh'] if w['mode']=='charge' else w['serve_kwh']
        wins.append({'mode':w['mode'],'label':MODE_LABEL.get(w['mode'],w['mode']),'start':w['start'],'end':w['end'],'avg_price':avg,
                     'kwh':kwh,'end_soc_kwh':w['end_soc_kwh'],'text':explain(w['mode'],avg,kwh,horizon_avg)})
    current=next((w for w in wins if _t(w['start'])<=now<_t(w['end'])),None)
    upcoming=next((w for w in wins if _t(w['start'])>now),None)
    tail=[{'start':r['start'],'end':r['end'],'price':r['price_eur_kwh'],'load_kwh':r['load_kwh'],'pv_kwh':r['pv_kwh']}
          for r in (plan.get('multiday_forecast') or {}).get('rows',[])]
    comp=p.get('comparison') or {}
    hints=[]
    pv=plan.get('pv_source') or {}
    if pv.get('warning'):hints.append({'level':'info','text':'PV-Prognose: '+PV_WARNINGS.get(pv['warning'],str(pv['warning']))})
    for w in (plan.get('forecast_model') or {}).get('warnings',[]):
        if w!='no_artifact':hints.append({'level':'info','text':'Prognose-Lernen: '+str(w)})
    if (plan.get('efficiency') or {}).get('source')=='configured':
        hints.append({'level':'info','text':'Wirkungsgrad ist noch ein Startwert; er wird gemessen, sobald genug Daten vorliegen.'})
    return {
     'created_at':plan.get('created_at'),'valid_until':plan.get('valid_until'),'target_soc':plan.get('target_soc'),
     'expired':_t(plan['valid_until'])<now if plan.get('valid_until') else None,
     'reason':policy.get('reason'),'reason_code':policy.get('reason_code'),
     'now':current,'next':upcoming,
     'capacity_kwh':inputs.get('nominal_capacity_kwh'),'reserve_kwh':inputs.get('reserve_kwh'),
     'grid_charge_limit_kwh':inputs.get('grid_charge_limit_kwh'),'initial_kwh':inputs.get('initial_kwh'),'soc_percent':inputs.get('soc'),
     'horizon_avg_price':horizon_avg,
     'savings':{'cash_eur':comp.get('total_savings_eur'),'carryover_eur':comp.get('estimated_carryover_benefit_eur'),
                'note':'Simuliert, nicht gemessen: Vergleich mit „Wechselrichter dauernd an“ im bekannten Preiszeitraum.'},
     'intervals':intervals,'windows':wins,'tail':tail,'hints':hints}

# --- entity suggestions ---------------------------------------------------------------
ENERGY_UNITS={'kWh','Wh','MWh'}
KEYWORDS={
 'grid_import':('verbrauch','consumption','import','bezug','grid','netz','meter'),
 'grid_export':('production','einspeis','export','feed','netz','grid'),
 'pv_energy':('pv','solar','erzeugung','production','yield'),
 'inverter_energy':('wechselrichter','inverter','wr','output'),
 'charger_energy':('lade','charger','netzlade'),
 'battery_soc':('soc','ladestand','battery','akku'),
 'battery_kwh':('kwh','akku','battery','speicher','energy'),
 'battery_voltage':('voltage','spannung','battery','akku','bms'),
 'battery_in_energy':('in','charge','laden','battery','bms'),
 'battery_out_energy':('out','discharge','entladen','battery','bms'),
 'charger_switch':('lade','charger','netzlade'),
 'inverter_switch':('wechselrichter','inverter','wr'),
 'pv_forecast_today':('today','heute','forecast','prognose','production'),
 'pv_forecast_today_remaining':('remaining','rest','today','heute','forecast'),
 'pv_forecast_tomorrow':('tomorrow','morgen','forecast','prognose'),
 'price_entity':('price','preis','nordpool','epex','awattar','tibber','strom','electricity'),
 'ev_energy':('wallbox','car','auto','ev','charger','cee','lade'),
 'ev_soc':('soc','battery','charge'),'ev_target_soc':('target','limit','ziel'),'ev_plug':('plug','cable','stecker','connected'),
}
COUNTER_ROLES={'grid_import','grid_export','pv_energy','inverter_energy','charger_energy','battery_in_energy','battery_out_energy','ev_energy'}
FORECAST_ROLES={'pv_forecast_today','pv_forecast_today_remaining','pv_forecast_tomorrow'}

def _matches(role,state):
    eid=state['entity_id'];domain=eid.split('.')[0];attrs=state.get('attributes') or {};unit=attrs.get('unit_of_measurement')
    dclass=attrs.get('device_class')
    if role in COUNTER_ROLES:return domain=='sensor' and unit in ENERGY_UNITS
    if role in FORECAST_ROLES:return domain=='sensor' and unit in ENERGY_UNITS
    if role=='battery_kwh':return domain=='sensor' and unit in ENERGY_UNITS
    if role in ('battery_soc','ev_soc','ev_target_soc'):return domain in ('sensor','number') and unit=='%'
    if role=='battery_voltage':return domain=='sensor' and (dclass=='voltage' or unit=='V')
    if role in ('charger_switch','inverter_switch'):return domain=='switch'
    if role=='weather':return domain=='weather'
    if role=='price_entity':return domain=='sensor' and any(isinstance(v,list) and v and isinstance(v[0],dict) for v in attrs.values())
    if role=='ev_plug':return domain=='binary_sensor'
    return False

def suggest(role,states,query='',limit=12):
    """Entities that fit `role`, best keyword match first. `states` is HA's state list."""
    q=query.lower().strip();words=KEYWORDS.get(role,())
    scored=[]
    for s in states:
        if not _matches(role,s):continue
        name=(s['entity_id']+' '+str((s.get('attributes') or {}).get('friendly_name',''))).lower()
        if q and q not in name:continue
        # Earlier keywords weigh more; entities that are currently unavailable sink to the end.
        score=sum(len(words)-i for i,w in enumerate(words) if w in name)
        dead=s.get('state') in ('unavailable','unknown')
        scored.append(((dead,-score),s['entity_id'],{'entity_id':s['entity_id'],'name':(s.get('attributes') or {}).get('friendly_name') or s['entity_id'],
                       'state':s.get('state'),'unit':(s.get('attributes') or {}).get('unit_of_measurement')}))
    scored.sort(key=lambda x:(x[0],x[1]))
    return [x[2] for x in scored[:limit]]

# --- settings validation ----------------------------------------------------------------
def validate_prices(raw,errors):
    out={'provider':raw.get('provider') or 'tibber','tibber_home':(raw.get('tibber_home') or '').strip() or None,
         'entity':(raw.get('entity') or '').strip() or None,'attribute':(raw.get('attribute') or '').strip() or None,
         'bidding_zone':(raw.get('bidding_zone') or 'DE-LU').strip().upper(),'markup_ct':0.0,'vat_percent':0.0}
    if out['provider'] not in ('tibber','entity','spot'):errors['prices.provider']='Unbekannter Anbieter'
    if out['entity'] and not ENTITY_RE.match(out['entity']):errors['prices.entity']='Ungültige Entität'
    if out['provider']=='entity' and not out['entity']:errors['prices.entity']='Preis-Sensor angeben'
    if out['attribute'] and not NAME_RE.match(out['attribute']):errors['prices.attribute']='Ungültiger Attributname'
    if not re.match(r'^[A-Z0-9-]{2,12}$',out['bidding_zone']):errors['prices.bidding_zone']='Gebotszone wie DE-LU oder AT'
    for key,hi,msg in (('markup_ct',100,'Aufschlag zwischen 0 und 100 ct/kWh'),('vat_percent',30,'MwSt. zwischen 0 und 30 %')):
        v=raw.get(key)
        if v in (None,''):continue
        try:
            x=float(str(v).replace(',','.'))
            if not 0<=x<=hi:raise ValueError
            out[key]=x
        except (TypeError,ValueError):errors['prices.'+key]=msg
    return out

ENTITY_RE=re.compile(r'^[a-z_]+\.[a-z0-9_]+$')
NAME_RE=re.compile(r'^[a-z0-9_]+$')

def validate_settings(data):
    """Return (clean_settings_dict, errors). Unknown keys are dropped, bad values reported by field."""
    errors={};clean={'entities':{},'location':{},'battery':{},'prices':{}}
    for role,value in (data.get('entities') or {}).items():
        if role not in settings.ROLES:continue
        if role in settings.LISTS:
            items=[v.strip() for v in (value or []) if str(v).strip()]
            bad=[v for v in items if not ENTITY_RE.match(v)]
            if bad:errors['entities.'+role]='Ungültige Entität: '+', '.join(bad)
            clean['entities'][role]=items
        else:
            v=(value or '').strip() or None
            pattern=NAME_RE if role=='ev_window_helper' else ENTITY_RE
            if v and not pattern.match(v):errors['entities.'+role]='Ungültiger Name'
            clean['entities'][role]=v
    loc=data.get('location') or {}
    for key,lo,hi in (('latitude',-90,90),('longitude',-180,180)):
        raw=loc.get(key)
        if raw in (None,''):clean['location'][key]=None;continue
        try:
            v=float(raw)
            if not lo<=v<=hi:raise ValueError
            clean['location'][key]=round(v,2)    # about 1 km: enough for radiation, no exact address
        except (TypeError,ValueError):errors['location.'+key]=f'Zahl zwischen {lo} und {hi} erwartet'
    if (clean['location'].get('latitude') is None)!=(clean['location'].get('longitude') is None):
        errors['location.latitude']='Breiten- und Längengrad gemeinsam angeben'
    clean['prices']=validate_prices(data.get('prices') or {},errors)
    battery=data.get('battery') or {}
    for key,lo,hi,msg in (('capacity_kwh',1,100,'Kapazität zwischen 1 und 100 kWh erwartet'),
                          ('max_charge_kw',.1,50,'Leistung zwischen 0,1 und 50 kW erwartet'),
                          ('max_discharge_kw',.1,50,'Leistung zwischen 0,1 und 50 kW erwartet')):
        raw=battery.get(key)
        if raw in (None,''):clean['battery'][key]=None;continue
        try:
            v=float(str(raw).replace(',','.'))
            if not lo<=v<=hi:raise ValueError
            clean['battery'][key]=v
        except (TypeError,ValueError):errors['battery.'+key]=msg
    raw=(data.get('tariff') or {}).get('price_floor_eur_kwh')
    clean['tariff']={'price_floor_eur_kwh':None}
    if raw not in (None,''):
        try:
            v=float(str(raw).replace(',','.'))
            if not 0<=v<=1:raise ValueError
            clean['tariff']['price_floor_eur_kwh']=v
        except (TypeError,ValueError):errors['tariff.price_floor_eur_kwh']='Preis zwischen 0 und 1 €/kWh erwartet'
    return clean,errors
