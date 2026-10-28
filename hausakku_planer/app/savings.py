"""Measured savings: actual operation vs. 'WR always on, never grid charge' (stdlib only).

Both sides use the same measured hours: house load without vehicles
(grid + WR - charger - export - EV), measured DC PV and real Tibber prices.
Vehicle charging (Tesla/CEE, City El) is excluded on both sides, so it cancels.
The counterfactual starts with the measured battery energy and replays 'serve' with
the planner's physics. Both end with different battery contents; the difference is
reported in kWh and valued conservatively at the price floor x discharge efficiency.
Limitations: hourly energies with hourly mean prices (quarter-hour timing inside an
hour is lost); PV curtailed in reality while the battery was full and the WR off is
missing from the measurement, which slightly favours the counterfactual's cost.
"""
import math
from datetime import datetime,timedelta,timezone
from forecast import TZ
from optimizer import Interval,_replay

UTC=timezone.utc


def balance(hours,prices,start_kwh,end_kwh,params,inventory_value_eur_kwh):
    """hours: [{start, grid, wr, charger, export, ev, pv}] hourly kWh; prices: {hour start: EUR/kWh}."""
    rows=[];actual=[];skipped=0
    for h in sorted(hours,key=lambda r:r['start']):
        values=[h.get(k) for k in ('grid','wr','charger','export','ev','pv')]
        price=prices.get(h['start'])
        if price is None or any(v is None or not math.isfinite(v) for v in values):
            skipped+=1;continue
        grid,wr,charger,export,ev,pv=values
        load=max(0.,grid+wr-charger-export-ev)
        start=datetime.fromtimestamp(h['start'],UTC)
        rows.append(Interval(start,start+timedelta(hours=1),price,load,max(0.,pv)))
        actual.append(dict(start=h['start'],price=price,house_grid=max(0.,grid-ev),charger=charger,wr=wr,load=load,pv=max(0.,pv)))
    if not rows:raise ValueError('No complete measured hours')
    if any((b.start-a.start).total_seconds()!=3600 for a,b in zip(rows,rows[1:])):
        raise ValueError('Measured hours are not contiguous')
    counterfactual=_replay(rows,['serve']*len(rows),params)
    actual_cost=math.fsum(a['house_grid']*a['price'] for a in actual)
    cf_cost=counterfactual['cost_eur']
    inventory=end_kwh-counterfactual['terminal_kwh']
    charged=math.fsum(a['charger'] for a in actual)
    served=math.fsum(a['wr'] for a in actual)
    days={}
    for a,f in zip(actual,counterfactual['intervals']):
        day=datetime.fromtimestamp(a['start'],UTC).astimezone(TZ).date().isoformat()
        d=days.setdefault(day,{'actual_eur':0.,'counterfactual_eur':0.,'load_kwh':0.,'pv_kwh':0.})
        d['actual_eur']+=a['house_grid']*a['price'];d['counterfactual_eur']+=f['cost_eur']
        d['load_kwh']+=a['load'];d['pv_kwh']+=a['pv']
    return {
        'hours':len(rows),'skipped_hours':skipped,
        'actual_cost_eur':actual_cost,'counterfactual_cost_eur':cf_cost,'cash_saving_eur':cf_cost-actual_cost,
        'start_kwh':start_kwh,'end_kwh':end_kwh,'counterfactual_end_kwh':counterfactual['terminal_kwh'],
        'inventory_difference_kwh':inventory,'inventory_value_eur':inventory*inventory_value_eur_kwh,
        'saving_incl_inventory_eur':cf_cost-actual_cost+inventory*inventory_value_eur_kwh,
        'grid_charged_ac_kwh':charged,
        'mean_charge_price_eur_kwh':math.fsum(a['charger']*a['price'] for a in actual)/charged if charged>1e-9 else None,
        'battery_served_ac_kwh':served,
        'mean_served_price_eur_kwh':math.fsum(a['wr']*a['price'] for a in actual)/served if served>1e-9 else None,
        'house_load_kwh':math.fsum(a['load'] for a in actual),'pv_kwh':math.fsum(a['pv'] for a in actual),
        'days':days,
    }

