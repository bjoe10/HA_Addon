import unittest
from datetime import datetime,timedelta,timezone
from optimizer import Params
from savings import balance
UTC=timezone.utc

def hour(i,grid,wr=0.,charger=0.,pv=0.,ev=0.):
    return {'start':datetime(2026,10,19,tzinfo=UTC).timestamp()+3600*i,'grid':grid,'wr':wr,'charger':charger,'export':0.,'ev':ev,'pv':pv}

class SavingsTests(unittest.TestCase):
    def params(self,initial):
        return Params(10,1,initial,'dc',max_charge_kw=1.13,max_discharge_kw=2,discharge_efficiency=.8,charge_efficiency=.75/.8,grid_charge_limit_kwh=9)
    def test_holding_for_the_expensive_hour_saves_money(self):
        prices={datetime(2026,10,19,tzinfo=UTC).timestamp()+3600*i:p for i,p in enumerate((.2,.5))}
        # Actual: WR off at 20 ct (1 kWh from grid), WR supplies the 50 ct hour completely.
        actual=[hour(0,grid=1.),hour(1,grid=0.,wr=1.)]
        # Without steering the 20 ct hour drains the battery, leaving only 0.2 kWh AC for the 50 ct hour.
        r=balance(actual,prices,start_kwh=2.5,end_kwh=2.5-1/.8,params=self.params(2.5),inventory_value_eur_kwh=.14)
        self.assertAlmostEqual(r['actual_cost_eur'],.2)
        self.assertAlmostEqual(r['counterfactual_cost_eur'],.4)
        self.assertAlmostEqual(r['cash_saving_eur'],.2)
        self.assertAlmostEqual(r['inventory_difference_kwh'],.25)
        self.assertAlmostEqual(r['saving_incl_inventory_eur'],.2+.25*.14)
    def test_vehicle_charging_cancels_and_gaps_are_reported(self):
        prices={datetime(2026,10,19,tzinfo=UTC).timestamp()+3600*i:.3 for i in range(2)}
        r=balance([hour(0,grid=5.,ev=5.),hour(1,grid=None)],prices,1.,1.,self.params(1.),.1)
        self.assertEqual(r['hours'],1);self.assertEqual(r['skipped_hours'],1)
        self.assertAlmostEqual(r['actual_cost_eur'],0.);self.assertAlmostEqual(r['counterfactual_cost_eur'],0.)
        with self.assertRaises(ValueError):balance([],{},1.,1.,self.params(1.),.1)

if __name__=='__main__':unittest.main()
