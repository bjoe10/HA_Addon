"""Causal local multi-day baselines and prospective decision audit (stdlib only).
Forecast intervals are NEVER execution permissions. No historic prices are invented.
The production policy uses an uncertainty-discounted recharge-aware continuation.
Its final inventory is worthless: there is exactly one continuation credit.
"""
from dataclasses import replace,asdict
from datetime import date,datetime,timedelta,timezone
from statistics import median
from pathlib import Path
import json,math,sqlite3,hashlib
from forecast import TZ,estimate
from optimizer import Interval,_flow,_interpolate,Params,optimize,_replay

UTC=timezone.utc

def _stamp(value):
    if isinstance(value,(float,int)):return float(value)
    dt=datetime.fromisoformat(value) if isinstance(value,str) else value
    if dt.tzinfo is None:raise ValueError('Aware timestamp required')
    return dt.timestamp()

def _db(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path)
    db.executescript('''CREATE TABLE IF NOT EXISTS prices (
      target REAL, issued REAL, price REAL, PRIMARY KEY(target,issued));
      CREATE TABLE IF NOT EXISTS weather (
      target REAL, issued REAL, payload TEXT, PRIMARY KEY(target,issued));
      CREATE TABLE IF NOT EXISTS issues (
      id TEXT PRIMARY KEY, issued REAL, payload TEXT, outcome TEXT);''')
    return db

def archive_prices(path,snapshot):
    """Keep every actually observed Tibber vintage, including future known targets."""
    issue=_stamp(snapshot['collected_at'])
    with _db(path) as db:
        for row in snapshot['prices']:
            target=_stamp(row['start_time']);price=float(row['price'])
            if not math.isfinite(price):raise ValueError('Nonfinite price')
            old=db.execute('SELECT price FROM prices WHERE target=? AND issued=?',(target,issue)).fetchone()
            if old is not None and old[0]!=price:raise ValueError('Conflicting price vintage')
            db.execute('INSERT OR IGNORE INTO prices VALUES (?,?,?)',(target,issue,price))

def archive_weather(path,snapshot):
    """Keep every hourly DWD forecast vintage with all raw fields for later PV calibration."""
    issue=_stamp(snapshot['collected_at'])
    raw=snapshot.get('raw',{}).get('weather',{})
    raw=raw.get('data',raw) if isinstance(raw,dict) else {}
    rows=[]
    for forecast in raw.get('service_response',{}).values():
        rows+=forecast.get('forecast',[]) if isinstance(forecast,dict) else []
    count=0
    with _db(path) as db:
        for row in rows:
            try:target=_stamp(str(row['datetime']))
            except (KeyError,TypeError,ValueError):continue
            db.execute('INSERT OR IGNORE INTO weather VALUES (?,?,?)',(target,issue,json.dumps(row,sort_keys=True)));count+=1
    return count

def read_prices(path,as_of):
    if not Path(path).exists():return []
    with _db(path) as db:
        rows=db.execute('SELECT target,issued,price FROM prices WHERE issued<=? ORDER BY target,issued',(_stamp(as_of),)).fetchall()
    latest={t:{'start':t,'issued_at':i,'price':p} for t,i,p in rows}
    return list(latest.values())

def seed_price_archive(path,root,as_of):
    """Import original saved vintages, never create retrospective forecast issues."""
    count=0
    for file in sorted(Path(root).glob('*.json')):
        snapshot=json.loads(file.read_text())
        if _stamp(snapshot['collected_at'])>_stamp(as_of):continue
        archive_prices(path,snapshot);archive_weather(path,snapshot);count+=1
    return {'snapshots':count,'price_intervals':len(read_prices(path,as_of))}

def assess_promotion(daily):
    """Fixed chronological gate; seven-day embargo prevents overlapping tails.
    One predeclared price candidate, no test-driven candidate shopping.
    """
    dates=sorted(daily);test=dates[-14:];validation=dates[-35:-21]
    enough=len(validation)>=14 and len(test)>=14
    # A calendar embargo, not only seven missing observations.
    if enough:
        enough=(_stamp(test[0]+'T00:00:00+00:00')-_stamp(validation[-1]+'T00:00:00+00:00'))>=8*86400
    checks=[]
    for section in (validation,test):
        rows=[daily[d] for d in section]
        if not rows:checks.append(False);continue
        b=sum(r['price_baseline_mae'] for r in rows)
        c=sum(r['price_candidate_mae'] for r in rows)
        deltas=[r['decision_costs_eur']['candidate']-r['decision_costs_eur']['baseline_tail'] for r in rows]
        errors_b=sorted(r['price_baseline_mae'] for r in rows)
        errors_c=sorted(r['price_candidate_mae'] for r in rows)
        checks.append(b>0 and c<=.95*b and errors_c[math.ceil(.9*len(rows))-1]<=1.05*errors_b[math.ceil(.9*len(rows))-1]
                      and sum(deltas)<=-0.01*len(rows) and max(deltas)<=.25)
    return {'promoted':bool(enough and all(checks)),'validation_dates':validation,'test_dates':test,
            'embargo_days':7,'minimum_validation_days':14,'minimum_test_days':14,
            'reason':'fixed price-MAE/tail and paired decision-cost gates passed' if enough and all(checks) else
                     'insufficient independent chronological evidence or price/cost safeguards failed; retain baseline'}

def _eligible_prices(history,issue):
    # Completed observations only for training. Future KNOWN prices are a separate
    # fallback distribution; a later vintage cannot retroactively train a forecast.
    return [r for r in history if r['issued_at']<=issue.timestamp() and r['start']+900<=issue.timestamp()
            and issue.timestamp()-56*86400<=r['start'] and math.isfinite(r['price'])]

def _hourly_weather(snapshot):
    """Index DWD cloud values by instant; no sunshine-duration or irradiance is inferred."""
    by_start={}
    for row in snapshot.get('weather_forecasts',[]):
        try:
            stamp=datetime.fromisoformat(str(row['datetime']))
            cloud=float(row['cloud_coverage'])
        except (KeyError,TypeError,ValueError):
            continue
        if stamp.tzinfo is not None and math.isfinite(cloud) and 0.<=cloud<=100.:
            by_start[stamp.timestamp()]={'cloud_coverage':cloud,'condition':row.get('condition')}
    return by_start


def _cloud_pv_factor(cloud_coverage):
    """Conservative heuristic for a downside scenario, not a calibrated PV model."""
    return min(1.,max(.25,1.-float(cloud_coverage)/100.))


def _daily_price_profiles(snapshot,hist,issue,shape_days=28):
    """Complete local days from observed history plus prices KNOWN at issue time.
    Returns {date: (daily mean, {hour: hourly mean})}; incomplete days are skipped.
    """
    points={r['start']:r['price'] for r in hist}
    for row in snapshot['prices']:points[_stamp(row['start_time'])]=float(row['price'])
    days={}
    for stamp,price in points.items():days.setdefault(datetime.fromtimestamp(stamp,TZ).date(),[]).append((stamp,price))
    result={}
    for day,values in days.items():
        if day<issue.date()-timedelta(days=shape_days):continue
        lo=datetime.combine(day,datetime.min.time(),TZ).timestamp()
        hi=datetime.combine(day+timedelta(days=1),datetime.min.time(),TZ).timestamp()
        if len(values)!=round((hi-lo)/900):continue
        hourly={}
        for stamp,price in values:hourly.setdefault(datetime.fromtimestamp(stamp,TZ).hour,[]).append(price)
        result[day]=(sum(p for _,p in values)/len(values),{h:sum(v)/len(v) for h,v in hourly.items()})
    return result


def shaped_price_model(snapshot,hist,issue,persistence=.7,long_days=28,weekday=False):
    """Daily shape plus level anchored on the last complete KNOWN day.
    level(d) = long + (known - long) * persistence**d + w[day] - w[anchor] * persistence**d,
    d = days after that known day. Shape: median hourly deviation from the daily mean
    over 28 days (additive, so negative prices stay valid). long: median daily mean over
    long_days. w: optional weekday offsets, median deviation of a day's mean from its
    centred 7-day mean over 56 days. Windows count back from the anchor day.
    Backtest 2026 (reconstructed Tibber prices, 3-day horizon, hourly MAE ct):
    flat 56-day median 5.65/6.44, persistence .5 + 28 days 4.06/4.22,
    persistence .3 + 56 days + weekday 3.77/4.15 (Jan-Jun selection / Jul-Oct test).
    """
    if not 0<=persistence<=1:raise ValueError('Price persistence must be in 0..1')
    if not 1<=long_days<=56:raise ValueError('Long price window must be 1..56 days')
    profiles=_daily_price_profiles(snapshot,hist,issue,shape_days=max(28,long_days,56 if weekday else 0)+2)
    known_days={datetime.fromtimestamp(_stamp(r['start_time']),TZ).date() for r in snapshot['prices']}
    anchors=sorted(d for d in profiles if d in known_days)
    if not anchors:return None
    anchor=anchors[-1]
    past={d:v for d,v in profiles.items() if d<=anchor}
    shape=[]
    for hour in range(24):
        deviations=[hourly[hour]-mean for d,(mean,hourly) in past.items() if (anchor-d).days<28 and hour in hourly]
        shape.append(median(deviations) if deviations else 0.)
    offsets=[0.]*7
    if weekday:
        deviations={}
        for d,(mean,_) in past.items():
            if (anchor-d).days>=56:continue
            window=[past[d+timedelta(days=k)][0] for k in range(-3,4) if d+timedelta(days=k) in past]
            if len(window)==7:deviations.setdefault(d.weekday(),[]).append(mean-sum(window)/7)
        offsets=[median(deviations[i]) if deviations.get(i) else 0. for i in range(7)]
    return {'anchor_date':anchor.isoformat(),'known_level':profiles[anchor][0],
            'long_level':median(mean for d,(mean,_) in past.items() if (anchor-d).days<long_days),
            'persistence':persistence,'long_days':long_days,'weekday_offsets':offsets,
            'shape':shape,'profile_days':len(past)}


def shaped_price(model,dt):
    anchor=date.fromisoformat(model['anchor_date'])
    decay=model['persistence']**max(0,(dt.date()-anchor).days)
    offsets=model.get('weekday_offsets',[0.]*7)
    level=(model['long_level']+(model['known_level']-model['long_level'])*decay
           +offsets[dt.weekday()]-offsets[anchor.weekday()]*decay)
    return level+model['shape'][dt.hour]


def _declination(day):
    return 23.44*math.sin(math.radians(360/365*(day.timetuple().tm_yday-81)))


def seasonal_pv_model(dataset,issue,neighbours=21):
    """Complete measured PV days before the issue date, keyed by UTC hour.
    Shading depends on sun position; equal solar declination (spring/autumn
    mirror) plus UTC hour approximates it without any panel geometry.
    """
    by_day={}
    for r in (dataset or {}).get('hours',[]):
        pv=r.get('pv_kwh')
        if pv is None or not math.isfinite(pv) or pv<0:continue
        local=datetime.fromtimestamp(r['start'],TZ).date()
        if local>=issue.date():continue
        by_day.setdefault(local,{})[datetime.fromtimestamp(r['start'],UTC).hour]=by_day.get(local,{}).get(datetime.fromtimestamp(r['start'],UTC).hour,0.)+pv
    counts={}
    for r in (dataset or {}).get('hours',[]):
        if r.get('pv_kwh') is not None:
            local=datetime.fromtimestamp(r['start'],TZ).date();counts[local]=counts.get(local,0)+1
    complete={}
    for day,hours in by_day.items():
        lo=datetime.combine(day,datetime.min.time(),TZ).timestamp()
        hi=datetime.combine(day+timedelta(days=1),datetime.min.time(),TZ).timestamp()
        if counts.get(day)==round((hi-lo)/3600):complete[day]=[hours.get(h,0.) for h in range(24)]
    if len(complete)<neighbours:return None
    return {'days':complete,'neighbours':neighbours}


def seasonal_pv_day(model,day):
    """Mean hourly profile and sorted totals of the nearest-declination past days."""
    target=_declination(day)
    near=sorted(model['days'],key=lambda d:(abs(_declination(d)-target),abs((day-d).days)))[:model['neighbours']]
    profile=[sum(model['days'][d][h] for d in near)/len(near) for h in range(24)]
    return {'profile':profile,'totals':sorted(sum(model['days'][d]) for d in near),
            'mean_total':sum(profile),'matched_from':min(near).isoformat(),'matched_to':max(near).isoformat()}


def _quantile(values,q):
    position=q*(len(values)-1);lo=math.floor(position);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(position-lo)


def build_tail(snapshot,data,end,dataset,history,days=3,evidence=None,price_model='flat_median',persistence=.7,
               price_floor=None,weather_weight=0.,pv_model='hourly_median28',radiation_pv=None,
               long_days=28,weekday=False,load_estimator='median',load_half_life=7.):
    issue=datetime.fromisoformat(snapshot['collected_at']).astimezone(TZ)
    end=end.astimezone(TZ)
    if not 1<=days<=7:raise ValueError('Tail days must be 1..7')
    if price_model not in ('flat_median','daily_shape'):raise ValueError('Unknown tail price model')
    if price_floor is not None and not math.isfinite(price_floor):raise ValueError('Price floor must be finite')
    if not 0<=weather_weight<=1:raise ValueError('Weather weight must be in 0..1')
    if pv_model not in ('hourly_median28','seasonal_declination'):raise ValueError('Unknown tail PV model')
    seasonal=seasonal_pv_model(dataset,issue) if pv_model=='seasonal_declination' else None
    seasonal_days={}
    # Forecast-only floor: fixed tariff parts bound future prices from below unless the
    # exchange price turns negative. Known Tibber prices are never clipped.
    floor=(lambda price:max(price_floor,price)) if price_floor is not None else (lambda price:price)
    buckets={}
    for r in (dataset or {}).get('hours',[]):
        dt=datetime.fromtimestamp(r['start'],TZ)
        if not issue.date()-timedelta(days=56)<=dt.date()<issue.date():continue
        buckets[r['start']]=r
    hist=_eligible_prices(history,issue)
    # Conservative fallback: lower quartile of actually known prices, not an
    # assumed expensive Monday. Negative prices are legitimate, not missing.
    known=sorted(float(r['price']) for r in snapshot['prices'])
    fallback=known[(len(known)-1)//4]
    central=median([r['price'] for r in hist]) if hist else fallback
    price_spread=median([abs(r['price']-central) for r in hist]) if hist else (max(known)-min(known))/2
    shaped=shaped_price_model(snapshot,hist,issue,persistence,long_days,weekday) if price_model=='daily_shape' else None
    profile=data['profile'];rows=[];candidate=[];baseline_prices=[];weather=_hourly_weather(snapshot);weather_adjustments={}
    # UTC stepping preserves both repeated DST hours and skips nonexistent ones.
    stop=datetime.combine(end.date()+timedelta(days=days),datetime.min.time(),TZ).timestamp()
    t=end.timestamp()
    while t<stop:
        dt=datetime.fromtimestamp(t,TZ);next_t=min(t+3600,stop);hours=(next_t-t)/3600
        weekend=dt.weekday()>=5;group='weekend' if weekend else 'weekday'
        loads=[];grouped=[];pvs=[];shape=[]
        for stamp,r in buckets.items():
            source=datetime.fromtimestamp(stamp,TZ)
            if source.hour!=dt.hour:continue
            load=r.get('load_kwh');pv=r.get('pv_kwh')
            if load is not None and math.isfinite(load) and load>=0:
                sample=(load,(issue.timestamp()-stamp)/86400)
                loads.append(sample)
                if (source.weekday()>=5)==weekend:grouped.append(sample)
            if source.date()>=issue.date()-timedelta(days=28) and pv is not None and math.isfinite(pv) and pv>=0:pvs.append(pv)
        load=estimate(grouped,load_estimator,load_half_life) if len(grouped)>=3 else estimate(loads,load_estimator,load_half_life) if loads else (
            profile[group][dt.hour] if profile['samples'][group][dt.hour]>=3 else profile['all'][dt.hour])
        day=dt.date().isoformat()
        history_pv=median(pvs) if pvs else 0.
        # Calibrated Open-Meteo radiation PV replaces climatology and the DWD heuristics.
        radiation_used=bool(radiation_pv) and t in radiation_pv
        if radiation_used:
            pv=radiation_pv[t]
        elif day in data['pv_totals_corrected_kwh']:
            # SolarForecast total is one input for the central path, distributed
            # across hours by recent measured shape; DWD remains a separate downside case.
            shape=[median(v) if v else 0. for v in snapshot['pv_shape_samples']]
            lo=datetime.combine(dt.date(),datetime.min.time(),TZ).timestamp()
            hi=datetime.combine(dt.date()+timedelta(days=1),datetime.min.time(),TZ).timestamp()
            denom=sum(max(0.,shape[datetime.fromtimestamp(x,TZ).hour]) for x in range(int(lo),int(hi),3600))
            pv=data['pv_totals_corrected_kwh'][day]*max(0.,shape[dt.hour])/denom if denom else 0.
        elif seasonal:
            if day not in seasonal_days:
                info=seasonal_pv_day(seasonal,dt.date())
                # Day-level DWD mapping: mean cloud weighted by expected PV picks a
                # quantile of REAL matched-season day totals (rank assumption, uncalibrated).
                lo=datetime.combine(dt.date(),datetime.min.time(),TZ).timestamp()
                hi=datetime.combine(dt.date()+timedelta(days=1),datetime.min.time(),TZ).timestamp()
                weighted=covered=0.
                for x in range(int(lo),int(hi),3600):
                    w=info['profile'][datetime.fromtimestamp(x,UTC).hour]
                    if x in weather:weighted+=weather[x]['cloud_coverage']*w;covered+=w
                info['cloud']=weighted/covered if covered>=.8*info['mean_total'] and covered>0 else None
                info['weather_total']=None if info['cloud'] is None else _quantile(info['totals'],min(.95,max(.05,1-info['cloud']/100)))
                seasonal_days[day]=info
            info=seasonal_days[day]
            pv=info['profile'][datetime.fromtimestamp(t,UTC).hour]
        else:
            pv=history_pv
        wx=weather.get(t)
        weather_pv=None;central_pv=pv
        if radiation_used:
            pass
        elif seasonal and day in seasonal_days and day not in data['pv_totals_corrected_kwh']:
            info=seasonal_days[day]
            if info['weather_total'] is not None and info['mean_total']>0:
                weather_pv=pv*info['weather_total']/info['mean_total']
                central_pv=(1-weather_weight)*pv+weather_weight*weather_pv
                adjustment=weather_adjustments.setdefault(day,{'baseline_pv_kwh':info['mean_total'],
                    'weather_low_pv_kwh':info['weather_total'],'mean_cloud_coverage':info['cloud'],'method':'seasonal_quantile'})
        elif wx and history_pv>0. and pv>0.:
            factor=_cloud_pv_factor(wx['cloud_coverage'])
            weather_pv=min(pv,history_pv*factor)
            # Optional central blend with the cloud estimate; the low scenario stays pure DWD.
            central_pv=(1-weather_weight)*pv+weather_weight*weather_pv
            if factor<1.:
                adjustment=weather_adjustments.setdefault(day,{'baseline_pv_kwh':0.,'weather_low_pv_kwh':0.,
                    'cloud_weighted_sum':0.,'cloud_weight':0.,'hours':0})
                adjustment['baseline_pv_kwh']+=pv*hours
                adjustment['weather_low_pv_kwh']+=weather_pv*hours
                weight=history_pv*hours
                adjustment['cloud_weighted_sum']+=wx['cloud_coverage']*weight
                adjustment['cloud_weight']+=weight
                adjustment['hours']+=1
        matched_rows=[r for r in hist if datetime.fromtimestamp(r['start'],TZ).hour==dt.hour
                      and datetime.fromtimestamp(r['start'],TZ).weekday()==dt.weekday()]
        matched_days={datetime.fromtimestamp(r['start'],TZ).date() for r in matched_rows}
        matches=[r['price'] for r in matched_rows]
        # Learned weekday candidate retained only for prospective validation; NOT
        # promoted on an in-sample fit or a hand-picked Monday story.
        cp=.5*median(matches)+.5*central if len(matched_days)>=4 else central
        candidate.append(cp)
        base_price=floor(shaped_price(shaped,dt) if shaped else central)
        baseline_prices.append(base_price)
        rows.append({'start':dt.isoformat(),'end':datetime.fromtimestamp(next_t,TZ).isoformat(),
                     'price_eur_kwh':cp if (evidence or {}).get('promoted') else base_price,
                     'load_kwh':load*hours,'pv_kwh':central_pv*hours,
                     'weather_pv_kwh':weather_pv*hours if weather_pv is not None else None,
                     'weather_cloud_coverage':wx['cloud_coverage'] if wx else None})
        t=next_t
    for adjustment in weather_adjustments.values():
        if adjustment.get('method')=='seasonal_quantile':continue
        weight=adjustment.pop('cloud_weight')
        weighted=adjustment.pop('cloud_weighted_sum')
        adjustment['mean_cloud_coverage']=weighted/weight if weight else None
    return {'schema_version':3,'future_grid_charge_model':True,'issued_at':issue.isoformat(),'rows':rows,
            'price_model':'weekday56_shrunk_validated' if (evidence or {}).get('promoted') else
                           'daily_shape_level_reversion_baseline' if shaped else
                           'rolling_observed_median_baseline' if hist else 'observed_known_price_baseline',
            'candidate_model':'weekday56_shrunk_seasonal_candidate','candidate_prices':candidate,
            'promoted':bool((evidence or {}).get('promoted')),'baseline_price':central,
            'baseline_prices':baseline_prices,'shaped_price_model':shaped,
            'price_floor_eur_kwh':price_floor,'pv_weather_weight':weather_weight,
            'promotion_evidence':evidence or {'promoted':False,'reason':'no independent prospective outcomes'},
                        'price_training_intervals':len(hist),
            'price_spread_eur_kwh':price_spread,'days':days,
            'pv_model':'openmeteo_radiation_calibrated' if radiation_pv and any(_stamp(r['start']) in radiation_pv for r in rows) else
                       ('seasonal_declination_with_dwd_quantile' if weather_adjustments else 'seasonal_declination') if seasonal else
                        'historical_28d_with_dwd_hourly_low_scenario' if weather_adjustments else 'recent_28d_climatology',
            'weather_adjustments':weather_adjustments,
            'weather_warning':snapshot.get('weather_forecast_warning'),
            'uncertainty':'Sensitivity scenarios, NOT calibrated confidence intervals.',
            'limitations':['Historical hourly PV is the central tail profile; DWD hourly cloud coverage creates an additional low-PV scenario only.',
              'The DWD integration provides cloud/condition forecasts here, not sunshine duration or solar irradiance; the cloud attenuation rule with a 25% floor is an uncalibrated downside heuristic.',
              'Recent 28-day PV / 56-day load climatology slowly adapts to season; not validated seasonal skill.',
              'No price candidate promotion without chronological prospective forecast AND decision-cost evidence.',
              'Future recharge is simulated under the same uncertain prices for every starting inventory; forecast actions are never execution permissions.']}

def scenario_rows(tail):
    raw=tail['rows']
    base=[Interval(start=datetime.fromisoformat(r['start']),end=datetime.fromisoformat(r['end']),
                   price_eur_kwh=r['price_eur_kwh'],load_kwh=r['load_kwh'],pv_kwh=r['pv_kwh']) for r in raw]
    spread=tail['price_spread_eur_kwh'];scenarios=[]
    for index,(dp,load_factor,pv_factor) in enumerate(((0.,1.,1.),(-spread,.85,1.35),(spread,1.1,.65))):
        rows=[]
        for source,row in zip(raw,base):
            pv=source.get('weather_pv_kwh') if index==2 else None
            if pv is None:pv=row.pv_kwh*pv_factor
            price=row.price_eur_kwh+dp
            if tail.get('price_floor_eur_kwh') is not None:price=max(tail['price_floor_eur_kwh'],price)
            rows.append(replace(row,price_eur_kwh=price,
                                load_kwh=row.load_kwh*load_factor,pv_kwh=pv))
        scenarios.append(rows)
    return scenarios

def continuation_curve(scenarios,p,allow_grid_charge=True,mean_weight=.5,end_value_eur_kwh=0.):
    """Recharge-aware DP; mean/lower-scenario blend, concave minorant.

    end_value_eur_kwh credits DC energy above reserve at the END of the tail (default
    zero). A price floor justifies a lower bound: every later kWh displaces at least
    floor-priced grid energy. It stays below the AC charge cost, so it never alone
    motivates grid charging.

    Common reserve-reference removes unavoidable tail imports. Slopes are clipped
    downwards (not upwards) to avoid creating value when PV displaces inventory.
    No credit below reserve; finite demand makes the highest units worth less.
    """
    step=max(.25,p.energy_step_kwh);grid=[0.,p.reserve_kwh]
    while grid[-1]<p.capacity_kwh-1e-9:grid.append(min(p.capacity_kwh,grid[-1]+step))
    grid=sorted(set(grid));values=[]
    if end_value_eur_kwh<0 or not math.isfinite(end_value_eur_kwh):raise ValueError('End value must be finite and nonnegative')
    p=replace(p,terminal_value_eur_kwh=0.,terminal_value_curve=())
    for rows in scenarios:
        future=[(-end_value_eur_kwh*max(0.,energy-p.reserve_kwh),) for energy in grid]
        for row in reversed(rows):
            current=[]
            for energy in grid:
                scores=[]
                for mode in (('hold','serve','charge') if allow_grid_charge else ('hold','serve')):
                    f=_flow(row,energy,mode,p)
                    scores.append(f['cost_eur']+_interpolate(grid,future,f['terminal_kwh'])[0])
                current.append((min(scores),))
            future=current
        base=future[grid.index(p.reserve_kwh)][0]
        values.append([max(0.,base-v[0]) for v in future])
    if not 0<=mean_weight<=1:raise ValueError('Scenario mean weight must be in 0..1')
    # mean_weight trades expected value against the least favourable scenario.
    raw=[mean_weight*sum(v[i] for v in values)/len(values)+(1-mean_weight)*min(v[i] for v in values) for i in range(len(grid))]
    curve=[(grid[0],0.)];slope=math.inf
    for i in range(1,len(grid)):
        width=grid[i]-grid[i-1]
        # Reserve creates an initial flat region; concavity starts AT reserve.
        if grid[i]<=p.reserve_kwh:value=0.
        else:
            slope=max(0.,min(slope,(raw[i]-raw[i-1])/width))
            value=min(raw[i],curve[-1][1]+slope*width)
        curve.append((grid[i],max(curve[-1][1],value)))
    return curve

def archive_issue(path,snapshot,tail,selected,baseline,candidate=None,baseline_tail=None):
    payload={'tail':tail,'selected':selected,'baseline':baseline,
             'candidate':candidate or selected,'baseline_tail':baseline_tail or selected}
    encoded=json.dumps(payload,sort_keys=True,allow_nan=False)
    key=hashlib.sha256(encoded.encode()).hexdigest()
    with _db(path) as db:db.execute('INSERT OR IGNORE INTO issues VALUES (?,?,?,NULL)',(key,_stamp(snapshot['collected_at']),encoded))
    return key

def score_issues(path,dataset,as_of):
    """Only score fully observed future tails. Store paired forecast and policy costs.
    Selection is frozen to baseline until >=14 validation +14 later test issues
    (distinct issue dates, seven-day embargo) pass price AND decision-cost gates.
    """
    now=_stamp(as_of);actual={r['start']:r for r in dataset.get('hours',[]) if r['start']+3600<=now}
    prices=read_prices(path,as_of);price_by={r['start']:r['price'] for r in prices}
    with _db(path) as db:
        for key,payload in db.execute('SELECT id,payload FROM issues WHERE outcome IS NULL').fetchall():
            p=json.loads(payload);tail=p['tail'];rows=[];base_errors=[];candidate_errors=[]
            for i,r in enumerate(tail['rows']):
                t=_stamp(r['start']);end=_stamp(r['end']);a=actual.get(t)
                stamps=list(range(int(t),int(end),900))
                if not a or a.get('load_kwh') is None or a.get('pv_kwh') is None or not all(x in price_by for x in stamps):break
                price=sum(price_by[x] for x in stamps)/len(stamps)
                # Schema 3 archives a per-hour baseline; older issues kept one flat price.
                base_errors.append(abs(price-(tail['baseline_prices'][i] if 'baseline_prices' in tail else tail['baseline_price'])))
                candidate_errors.append(abs(price-tail['candidate_prices'][i]))
                rows.append(Interval(datetime.fromtimestamp(t,TZ),datetime.fromtimestamp(end,TZ),price,a['load_kwh'],a['pv_kwh']))
            if len(rows)!=len(tail['rows']) or not rows or 'params' not in p['selected']:continue
            costs={}
            for label in ('selected','baseline','candidate','baseline_tail'):
                plan=p[label];observed=[]
                for f in plan['intervals']:
                    t=_stamp(f['start']);end=_stamp(f['end'])
                    a=actual.get(math.floor(t/3600)*3600);price=price_by.get(math.floor(t/900)*900)
                    if not a or a.get('load_kwh') is None or a.get('pv_kwh') is None or price is None:break
                    h=(end-t)/3600
                    observed.append(Interval(datetime.fromtimestamp(t,TZ),datetime.fromtimestamp(end,TZ),price,a['load_kwh']*h,a['pv_kwh']*h))
                if len(observed)!=len(plan['intervals']):break
                original=Params(**{**plan['params'],'terminal_value_eur_kwh':0.,'terminal_value_curve':(), 'decision_block_minutes':0})
                replay=_replay(observed,plan['modes'],original)
                params=replace(original,initial_kwh=replay['terminal_kwh'])
                # Every policy sees identical recharge opportunities; older archive
                # vintages retain their original no-charge evaluation contract.
                future_plan=optimize(rows,params)
                continuation=future_plan if tail.get('future_grid_charge_model') else future_plan['comparison']['optimized_no_charge']
                costs[label]=replay['cost_eur']+continuation['cost_eur']
            if len(costs)!=4:continue
            outcome={'available_after':now,
                     'cost_basis':'frozen_policy_replay_observed_hourly_energy_prorated',
                     'price_baseline_mae':sum(base_errors)/len(rows),'price_candidate_mae':sum(candidate_errors)/len(rows),
                     'decision_costs_eur':costs,'savings_vs_zero_terminal_policy_eur':costs['baseline']-costs['selected']}
            db.execute('UPDATE issues SET outcome=? WHERE id=?',(json.dumps(outcome),key))
        outcomes=db.execute('SELECT issued,outcome FROM issues WHERE outcome IS NOT NULL ORDER BY issued').fetchall()
        pending=db.execute('SELECT count(*) FROM issues WHERE outcome IS NULL').fetchone()[0]
    # Multiple intraday issues are not independent days.
    daily={datetime.fromtimestamp(t,TZ).date().isoformat():json.loads(o) for t,o in outcomes if json.loads(o)['available_after']<=now}
    assessment=assess_promotion(daily)
    return {'scored':sum(json.loads(o)['available_after']<=now for _,o in outcomes),'pending':pending,'independent_days':len(daily),
            **assessment,
            'outcomes_by_day':daily}
