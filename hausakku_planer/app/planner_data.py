"""Build audit-friendly forecast inputs. All provisional assumptions remain explicit."""
import math
from datetime import datetime,timedelta
from statistics import median
from forecast import TZ,load_profile,pv_calibration,price_intervals
import settings

def value(states,key):
    v=float(states[key]['state'])
    if not math.isfinite(v): raise ValueError('Non-finite state '+key)
    return v

def optional_value(states,key):
    """SolarForecast sensors are 'unavailable' around midnight; that must not abort planning."""
    if not key:return None
    try:return value(states,key)
    except (KeyError,TypeError,ValueError):return None

def prepare(snapshot,config):
    now=datetime.fromisoformat(snapshot['planning_start']).astimezone(TZ)
    states=snapshot['states']
    entities=settings.current()
    soc=value(states,entities.entity('battery_soc'))
    kwh_entity=entities.entity('battery_kwh',required=False)
    initial=value(states,kwh_entity) if kwh_entity else None
    inferred=config.get('capacity_kwh') is None
    if inferred:
        if initial is None: raise ValueError('Akku-Kapazität (kWh) ist nicht eingerichtet')
        if not 5<=soc<=100: raise ValueError('Cannot infer capacity from low/invalid SOC')
        capacity=initial/(soc/100)
    else:
        capacity=float(config['capacity_kwh'])
        if initial is None:initial=capacity*soc/100
    # BMS rounding can report slightly above the configured capacity when full.
    if capacity<initial<=capacity*1.03:initial=capacity
    if not 0<=initial<=capacity or not 1<capacity<100: raise ValueError('Implausible battery capacity/state')
    reserve_fraction=float(config.get('reserve_fraction',.1))
    charge_fraction=float(config.get('grid_charge_max_soc_fraction',.9))
    if not 0<=reserve_fraction<=charge_fraction<=1: raise ValueError('Invalid reserve or grid-charge SOC boundary')
    profile=load_profile(snapshot['balances'],config.get('load_estimator','median'),float(config.get('load_half_life_days',7)),now)
    if any(v is None for v in profile['all']): raise ValueError('Missing historical load hours')
    calibration=pv_calibration(snapshot['pv_actual_by_day'],snapshot['pv_predicted_by_day'],now.date().isoformat())
    factor=calibration['factor'] if calibration['pairs']>=3 else 1.
    if not .1<=factor<=10: raise ValueError('PV calibration implausible; inspect source sensor configuration')
    intervals=price_intervals(snapshot['prices'],now)
    min_samples=config.get('minimum_group_samples',3)
    for r in intervals:
        start=r['start']; h=(r['end'].timestamp()-start.timestamp())/3600
        group='weekend' if start.weekday()>=5 else 'weekday'
        load=profile[group][start.hour] if profile['samples'][group][start.hour]>=min_samples else profile['all'][start.hour]
        r['load_kwh']=load*h
        r['pv_kwh']=0.
    # Historical PV shape is used only as a time distribution. Corrected forecast
    # sets its total; no generic sunny-day energy is invented.
    shape=[median(v) if v else 0. for v in snapshot['pv_shape_samples']]
    shape=[x if x>=.02 else 0. for x in shape]
    tomorrow=(now.date()+timedelta(days=1)).isoformat()
    raw_totals={now.date().isoformat():optional_value(states,entities.entity('pv_forecast_today_remaining',required=False)),
                tomorrow:optional_value(states,entities.entity('pv_forecast_tomorrow',required=False))}
    missing=sorted(day for day,total in raw_totals.items() if total is None)
    totals={day:total*factor for day,total in raw_totals.items() if total is not None}
    for day,total in totals.items():
        day_rows=[r for r in intervals if r['start'].date().isoformat()==day]
        # Normalize against the whole remaining day, not just the available price
        # horizon. Otherwise missing tomorrow prices would concentrate a full day's PV.
        dt=datetime.fromisoformat(day).replace(tzinfo=TZ)
        finish=dt+timedelta(days=1)
        first=max(dt.timestamp(),now.timestamp()) if day==now.date().isoformat() else dt.timestamp()
        denom=0.;t=first
        while t<finish.timestamp():
            local=datetime.fromtimestamp(t,TZ)
            boundary=min(finish.timestamp(),(math.floor(t/900)+1)*900)
            denom+=shape[local.hour]*(boundary-t)/3600
            t=boundary
        if total>0 and denom<=0: raise ValueError('No valid PV hourly shape')
        for r in day_rows:
            h=(r['end'].timestamp()-r['start'].timestamp())/3600
            r['pv_kwh']=max(0,total)*shape[r['start'].hour]*h/denom if denom else 0.
    return {'intervals':intervals,'initial_kwh':initial,'soc':soc,
       'nominal_capacity_kwh':capacity,'capacity_inferred':inferred,
       'reserve_kwh':capacity*reserve_fraction,
       'planning_capacity_kwh':capacity,
       'grid_charge_limit_kwh':capacity*charge_fraction,
       'profile':profile,'pv_calibration':calibration,'pv_totals_corrected_kwh':totals,
       'ha_pv_forecast_missing_days':missing,
       'forecast_warning':'Hourly PV shape is historical, not a weather-resolved forecast; savings are simulated, not measured.'}
