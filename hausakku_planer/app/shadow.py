"""Running savings of the control: actual operation vs. a shadow battery whose inverter is always on.

The shadow runs without interruption in quarter-hours, so energy held back at the end of a day or a
week is not lost at the boundary: the savings since the start are the summed cost difference plus the
current difference in battery contents. Day and week values are differences of that running total,
so they add up exactly.

Only quarter-hours in which the control's release switch was on for the whole quarter count. While it
is off (or data is missing) nothing is added; the battery difference at that moment is booked and the
shadow restarts from the measured battery the next time the control is on.

The shadow uses the planner's battery model with the measured discharge efficiency (when enough clean
discharge hours exist) and the measured share of the load that still comes from the grid while the
inverter serves (control lag, load peaks). The same model also replays the actual operation; its
deviation from the measured cost is reported as the model error. Stdlib only.
"""
import json, math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from optimizer import Interval, Params, _flow

TZ=ZoneInfo('Europe/Berlin');UTC=timezone.utc
STEP=900                    # seconds per counted interval (Tibber's quarter-hour)
BUCKET=300                  # Home Assistant's short-term statistics
METERS=('grid','wr','charger','export','pv','ev')
SETTLE=420                  # HA compiles a 5-minute statistic shortly after its period ends
MAX_CATCHUP=8*86400         # 5-minute statistics are purged after about ten days
RESIDUAL_MIN_KWH=2.         # serve energy needed before the learned grid share is used
RESIDUAL_MAX=.3
ACTIVE_ON='on'
KEEP_WEEKS=60


def new_state(now_ts):
    start=math.floor(now_ts/STEP)*STEP
    return {'version':1,'started':start,'last_end':start,'shadow_kwh':None,'model_kwh':None,'measured_kwh':None,
            'cash_eur':0.,'booked_inventory_eur':0.,'actual_eur':0.,'shadow_eur':0.,'model_eur':0.,
            'active_hours':0.,'inactive_hours':0.,'gap_hours':0.,'serve_load_kwh':0.,'serve_grid_kwh':0.,
            'control_on':None,'weeks':{}}


def monday(ts):
    d=datetime.fromtimestamp(ts,TZ).date()
    return (d-timedelta(days=d.weekday())).isoformat()


def residual_share(state):
    """Share of the load that came from the grid in measured serve quarters (0 until enough data)."""
    if state['serve_load_kwh']<RESIDUAL_MIN_KWH:return 0.
    return min(RESIDUAL_MAX,max(0.,state['serve_grid_kwh']/state['serve_load_kwh']))


def open_inventory_eur(state,value,measured=None):
    m=state['measured_kwh'] if measured is None else measured
    if state['shadow_kwh'] is None or m is None:return 0.
    return (m-state['shadow_kwh'])*value


def total_eur(state,value,measured=None):
    return state['cash_eur']+state['booked_inventory_eur']+open_inventory_eur(state,value,measured)


def _close(state,value):
    """Book the battery difference and stop the shadow; it restarts from the measured battery."""
    state['booked_inventory_eur']+=open_inventory_eur(state,value)
    state['shadow_kwh']=state['model_kwh']=None


def mode_of(row):
    return 'charge' if row['charger']>.01 else 'serve' if row['wr']>.01 else 'hold'


def advance(state,rows,params,value):
    """Add contiguous quarter-hours starting at state['last_end'].
    rows: {start, active, price, battery_kwh (at start), grid, wr, charger, export, pv, ev}; None = missing.
    value: EUR per kWh of battery contents (conservative), used for battery differences."""
    hours=STEP/3600
    for row in sorted(rows,key=lambda r:r['start']):
        if row['start']!=state['last_end']:raise ValueError('Viertelstunden nicht lückenlos')
        if row.get('battery_kwh') is not None:state['measured_kwh']=row['battery_kwh']
        state['weeks'].setdefault(monday(row['start']),round(total_eur(state,value),4))
        complete=row.get('price') is not None and all(row.get(k) is not None for k in METERS)
        active=bool(row.get('active'))
        state['control_on']=active
        if active and complete and state['shadow_kwh'] is None and row.get('battery_kwh') is not None:
            state['shadow_kwh']=state['model_kwh']=row['battery_kwh']
        if not active or not complete or state['shadow_kwh'] is None:
            if state['shadow_kwh'] is not None:_close(state,value)
            state['inactive_hours' if not active else 'gap_hours']+=hours
            state['last_end']=row['start']+STEP;continue
        price=row['price'];grid,wr,charger,export,pv,ev=(row[k] for k in ('grid','wr','charger','export','pv','ev'))
        load=max(0.,grid+wr-charger-export-ev);actual_grid=max(0.,grid-ev);pv=max(0.,pv)
        r=residual_share(state)
        start=datetime.fromtimestamp(row['start'],UTC);end=start+timedelta(seconds=STEP)
        shadow=_flow(Interval(start,end,price,load*(1-r),pv),state['shadow_kwh'],'serve',params)
        shadow_grid=shadow['grid_import_kwh']+load*r
        mode=mode_of(row)
        mp=replace(params,max_charge_kw=charger/hours) if mode=='charge' else params
        model=_flow(Interval(start,end,price,load*(1-r) if mode=='serve' else load,pv),state['model_kwh'],mode,mp)
        model_grid=model['grid_import_kwh']+(load*r if mode=='serve' else 0.)
        state['actual_eur']+=actual_grid*price;state['shadow_eur']+=shadow_grid*price;state['model_eur']+=model_grid*price
        state['cash_eur']+=(shadow_grid-actual_grid)*price
        state['shadow_kwh']=shadow['terminal_kwh'];state['model_kwh']=model['terminal_kwh']
        state['active_hours']+=hours
        # Learn the grid share while serving: mostly inverter-covered quarters, battery well above the reserve.
        if mode=='serve' and load>.02 and wr>=.5*load and row.get('battery_kwh') is not None and row['battery_kwh']>params.reserve_kwh+.5:
            state['serve_load_kwh']+=load;state['serve_grid_kwh']+=actual_grid
        state['last_end']=row['start']+STEP
    for key in sorted(state['weeks'])[:-KEEP_WEEKS]:del state['weeks'][key]
    return state


def skip_to(state,ts,value):
    """Jump over a period that can no longer be read (the short statistics are gone): nothing is counted."""
    if ts<=state['last_end']:return state
    if state['shadow_kwh'] is not None:_close(state,value)
    state['gap_hours']+=(ts-state['last_end'])/3600;state['last_end']=ts
    return state


def summary(state,value,measured=None):
    """What the sensor and the overview show: total since the start and this week, in EUR."""
    total=total_eur(state,value,measured)
    key=monday(state['last_end']);weeks=state['weeks']
    week_start=weeks.get(key,total)
    prev=(datetime.fromisoformat(key)-timedelta(days=7)).date().isoformat()
    keys=sorted(weeks)
    per_week=[{'start':k,'eur':round((weeks[keys[i+1]] if i+1<len(keys) else total)-weeks[k],2)} for i,k in enumerate(keys)]
    r=lambda v:round(v,2)
    return {'total_eur':r(total),'week_eur':r(total-week_start),
            'last_week_eur':r(week_start-weeks[prev]) if prev in weeks and key in weeks else None,
            'since':datetime.fromtimestamp(state['started'],TZ).isoformat(),
            'updated':datetime.fromtimestamp(state['last_end'],TZ).isoformat(),
            'control_on':state['control_on'],
            'cash_eur':r(state['cash_eur']),'inventory_eur':r(state['booked_inventory_eur']+open_inventory_eur(state,value,measured)),
            'active_hours':r(state['active_hours']),'inactive_hours':r(state['inactive_hours']),'gap_hours':r(state['gap_hours']),
            'actual_cost_eur':r(state['actual_eur']),'shadow_cost_eur':r(state['shadow_eur']),
            'model_deviation_eur':r(state['model_eur']-state['actual_eur']),
            'residual_share':round(residual_share(state),3),'battery_value_eur_kwh':round(value,4),
            'per_week':per_week[-12:]}


# ---------- inputs: parameters, valuation and quarter-hour rows from Home Assistant ----------

def model_params(config,calibration):
    """The planner's battery model; the measured discharge efficiency once 20 clean discharge hours exist."""
    cap=float(config['capacity_kwh']);cal=calibration or {}
    measured=cal.get('discharge_efficiency') if cal.get('discharge_hours',0)>=20 else None
    discharge=float(measured) if measured and .5<float(measured)<=1. else float(config['discharge_efficiency'])
    charge=float(cal['charge_efficiency']) if cal.get('valid') else float(config['roundtrip_efficiency'])/float(config['discharge_efficiency'])
    return Params(capacity_kwh=cap,reserve_kwh=cap*float(config['reserve_fraction']),initial_kwh=0.,pv_coupling='dc',
                  max_charge_kw=float(config['max_charge_kw']),max_discharge_kw=float(config['max_discharge_kw']),
                  discharge_efficiency=discharge,charge_efficiency=charge,
                  grid_charge_limit_kwh=cap*float(config['grid_charge_max_soc_fraction']))


def battery_value(config,prices,params,now_ts):
    """Conservative value of a kWh in the battery: the price floor (or the lowest price of the last 7 days) x discharge efficiency."""
    floor=config.get('tail_price_floor_eur_kwh')
    if floor is None:
        recent=[p for t,p in prices.items() if now_ts-7*86400<=t<=now_ts]
        floor=min(recent) if recent else 0.
    return max(0.,float(floor))*params.discharge_efficiency


def quarters(buckets,start,end):
    """5-minute values {t: kWh} summed to quarter-hours; a quarter missing any bucket is None."""
    out={}
    for q in range(int(start),int(end),STEP):
        parts=[buckets.get(float(t)) for t in range(q,q+STEP,BUCKET)]
        out[q]=None if any(v is None for v in parts) else sum(parts)
    return out


def active_quarters(states,start,end):
    """Quarter starts in which the release switch was on the whole time. states: [(ts, state)], the first one in force at `start`."""
    changes=sorted(states)
    out=set()
    for q in range(int(start),int(end),STEP):
        before=[s for t,s in changes if t<=q]
        inside=[s for t,s in changes if q<t<q+STEP]
        if before and before[-1]==ACTIVE_ON and all(s==ACTIVE_ON for s in inside):out.add(q)
    return out


def build_rows(start,end,meters,battery,active,prices):
    """meters: {role: {quarter: kWh or None}}, battery: {quarter: kWh at start}, active: set of quarters, prices: {quarter: EUR/kWh}."""
    return [{'start':q,'active':q in active,'price':prices.get(q),'battery_kwh':battery.get(q),
             **{k:meters.get(k,{}).get(q) for k in METERS}} for q in range(int(start),int(end),STEP)]


def load_state(path,now_ts):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return new_state(now_ts)


def save_state(path,state):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(state));tmp.replace(path)
