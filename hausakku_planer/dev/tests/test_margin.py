"""Grid charging has to clear a margin per kWh; value from estimated prices is discounted."""
import unittest
from dataclasses import replace
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import settings,views
from optimizer import Interval,Params,optimize
from operating_policy import choose_operation

TZ=ZoneInfo('Europe/Berlin')
START=datetime(2026,11,15,9,tzinfo=TZ)
# Round trip 0.74 as measured: 30 ct charged costs 40.5 ct per kWh used later.
P=Params(capacity_kwh=16.,reserve_kwh=1.6,initial_kwh=1.6,pv_coupling='dc',max_charge_kw=1.,max_discharge_kw=2.,
         discharge_efficiency=.85,charge_efficiency=.74/.85,energy_step_kwh=.05,grid_charge_limit_kwh=14.4)

def day(later_price):
    """Four cheap hours (30 ct, no load), then four hours of 0.5 kWh load at `later_price`."""
    rows=[]
    for h in range(8):
        t=START+timedelta(hours=h)
        rows.append(Interval(t,t+timedelta(hours=1),.30 if h<4 else later_price,0. if h<4 else .5,0.))
    return rows

def charged(rows,params):
    plan=choose_operation(rows,params,optimize(rows,params),{'minimum_savings_eur':0.})
    return sum(f['charger_ac_kwh'] for f in plan['plan']['intervals']),plan['reason_code']

class ChargeMarginTests(unittest.TestCase):
    def test_thin_gain_charges_without_margin_but_not_with_it(self):
        kwh,reason=charged(day(.43),P)                     # 2.5 ct above break-even
        self.assertGreater(kwh,1.);self.assertEqual(reason,'economic_optimization')
        kwh,reason=charged(day(.43),replace(P,charge_margin_eur_kwh=.05))
        self.assertEqual(kwh,0.);self.assertNotEqual(reason,'economic_optimization')

    def test_clear_gain_still_charges_with_margin(self):
        kwh,reason=charged(day(.50),replace(P,charge_margin_eur_kwh=.05))   # 9.5 ct above break-even
        self.assertGreater(kwh,1.);self.assertEqual(reason,'economic_optimization')

    def test_margin_is_planning_only(self):
        rows=day(.50)
        a=optimize(rows,P);b=optimize(rows,replace(P,charge_margin_eur_kwh=.05))
        self.assertEqual(a['modes'],b['modes']);self.assertAlmostEqual(a['cost_eur'],b['cost_eur'])   # reported cash unchanged

    def test_monday_recharge_at_40_ct_for_an_estimated_peak_is_refused(self):
        # Charging at 40.1 ct breaks even at 54 ct; an estimated value just above that used to be enough.
        t=START
        rows=[Interval(t,t+timedelta(hours=1),.401,0.,0.)]
        value=.47                                            # EUR per kWh in the battery, from estimated prices (55 ct x 0.85)
        curve=lambda discount:tuple((e,max(0.,e-1.6)*value*(1-discount)) for e in (0.,1.6,16.))
        kwh,_=charged(rows,replace(P,terminal_value_curve=curve(0.)))
        self.assertGreater(kwh,.5)
        kwh,_=charged(rows,replace(P,terminal_value_curve=curve(.10),charge_margin_eur_kwh=.05))
        self.assertEqual(kwh,0.)

class SettingsTests(unittest.TestCase):
    def test_defaults_and_overrides_reach_the_planner(self):
        cfg=settings.Settings({}).planner_config()
        self.assertEqual((cfg['grid_charge_margin_eur_kwh'],cfg['estimated_value_discount']),(.05,.1))
        cfg=settings.Settings({'tariff':{'grid_charge_margin_eur_kwh':0.,'estimated_value_discount':.2}}).planner_config()
        self.assertEqual((cfg['grid_charge_margin_eur_kwh'],cfg['estimated_value_discount']),(0.,.2))

    def test_validation(self):
        clean,err=views.validate_settings({'tariff':{'grid_charge_margin_eur_kwh':'0,08','estimated_value_discount':''}})
        self.assertEqual(clean['tariff']['grid_charge_margin_eur_kwh'],.08);self.assertIsNone(clean['tariff']['estimated_value_discount'])
        _,err=views.validate_settings({'tariff':{'grid_charge_margin_eur_kwh':'3','estimated_value_discount':'0.9'}})
        self.assertIn('tariff.grid_charge_margin_eur_kwh',err);self.assertIn('tariff.estimated_value_discount',err)

if __name__=='__main__':unittest.main()
