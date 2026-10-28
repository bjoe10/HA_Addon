"""New physical limits and block-decision regressions (fixtures, not live data)."""
import dataclasses
import itertools
import unittest
from datetime import timedelta
from optimizer import Interval,Params,optimize,_flow,_replay
from test_optimizer import params,series,START

class ChargingLimitTests(unittest.TestCase):
    def test_grid_stops_at_90_percent_while_pv_can_fill_physical_capacity(self):
        p=params(capacity_kwh=10,initial_kwh=8.9,grid_charge_limit_kwh=9)
        r=series([-.2],loads=[0])[0]
        f=_flow(r,p.initial_kwh,'charge',p)
        self.assertAlmostEqual(f['terminal_kwh'],9)
        self.assertAlmostEqual(f['charger_stored_dc_kwh'],.1)
        self.assertLess(f['charger_ac_kwh'],p.max_charge_kw)
        sun=dataclasses.replace(r,pv_kwh=2)
        f=_flow(sun,9,'hold',p)
        self.assertAlmostEqual(f['terminal_kwh'],10)
        self.assertEqual(f['charger_ac_kwh'],0)
    def test_no_grid_charging_above_ceiling_even_when_price_negative(self):
        p=params(capacity_kwh=10,initial_kwh=9.5,grid_charge_limit_kwh=9)
        f=_flow(series([-.4],loads=[0])[0],9.5,'charge',p)
        self.assertEqual(f['charger_ac_kwh'],0)
        self.assertEqual(f['terminal_kwh'],9.5)
    def test_pv_has_priority_over_grid_at_ceiling(self):
        p=params(capacity_kwh=10,initial_kwh=8.9,grid_charge_limit_kwh=9)
        f=_flow(series([-.4],loads=[0],pvs=[.5])[0],8.9,'charge',p)
        self.assertEqual(f['charger_ac_kwh'],0)
        self.assertAlmostEqual(f['terminal_kwh'],9.4)
    def test_new_negative_price_model_does_not_dump_grid_energy(self):
        p=params(capacity_kwh=.6,initial_kwh=.5,grid_charge_limit_kwh=.6)
        f=_flow(series([-.4],loads=[0])[0],.5,'charge',p)
        self.assertAlmostEqual(f['spill_dc_kwh'],0)
        self.assertAlmostEqual(f['terminal_kwh'],.6)
    def test_invalid_charge_limit_rejected(self):
        for limit in (-1,6,float('nan')):
            with self.subTest(limit=limit),self.assertRaises(ValueError):
                optimize(series([1]),params(grid_charge_limit_kwh=limit))
    def test_charge_limit_may_be_below_initial_state(self):
        p=params(capacity_kwh=10,initial_kwh=10,grid_charge_limit_kwh=9)
        self.assertEqual(optimize(series([.2],loads=[0]),p)['terminal_kwh'],10)

class DecisionBlockTests(unittest.TestCase):
    def test_same_mode_for_each_half_hour_but_physics_keeps_quarters(self):
        rows=series([.01,1,.01,1],minutes=15,loads=[.2]*4)
        r=optimize(rows,params(initial_kwh=1,decision_block_minutes=30))
        self.assertEqual(r['modes'][0],r['modes'][1])
        self.assertEqual(r['modes'][2],r['modes'][3])
        self.assertEqual(len(r['intervals']),4)
    def test_short_initial_and_final_partial_blocks_are_supported(self):
        rows=series([.1,.9,.2],start=START+timedelta(minutes=15),minutes=15)
        r=optimize(rows,params(decision_block_minutes=30))
        self.assertEqual(r['modes'][1],r['modes'][2])
    def test_block_optimizer_matches_block_bruteforce_with_charger_cap(self):
        rows=series([.05,.4,.8,.3],loads=[.1,.3,.2,.4],pvs=[0,.1,0,0],minutes=15)
        p=params(capacity_kwh=1,reserve_kwh=0,initial_kwh=.3,grid_charge_limit_kwh=.8,
                 decision_block_minutes=30,energy_step_kwh=.001)
        options=[]
        for modes in itertools.product(('hold','serve','charge'),repeat=2):
            options.append(_replay(rows,[m for m in modes for _ in range(2)],p)['cost_eur'])
        self.assertAlmostEqual(optimize(rows,p)['cost_eur'],min(options),places=5)
    def test_interval_crossing_block_boundary_fails_instead_of_wrong_duration(self):
        with self.assertRaises(ValueError):optimize(series([1],minutes=60),params(decision_block_minutes=30))

if __name__=='__main__':unittest.main()
