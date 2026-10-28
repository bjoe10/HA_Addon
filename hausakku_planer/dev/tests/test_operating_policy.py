"""Policy fixtures exercise summer/bypass selection without HA or real outputs."""
import unittest
from dataclasses import replace
from optimizer import optimize
from test_optimizer import params,series
from operating_policy import choose_operation

class OperatingPolicyTests(unittest.TestCase):
    def decide(self,rows,p=None,**config):
        p=p or params()
        return choose_operation(rows,p,optimize(rows,p),config)
    def test_pv_sufficient_under_margin_uses_normal_operation(self):
        rows=series([.2,.9,.4],loads=[.2,.2,.2],pvs=[0,2,0])
        r=self.decide(rows,params(initial_kwh=1))
        self.assertEqual(r['reason_code'],'energy_sufficient')
        self.assertEqual(r['plan']['modes'],['serve']*3)
        self.assertEqual(r['plan']['comparison']['total_savings_eur'],0)
    def test_lots_of_late_pv_does_not_hide_morning_shortfall(self):
        rows=series([.2,.9],loads=[1,1],pvs=[0,10])
        r=self.decide(rows,minimum_savings_eur=0)
        self.assertNotEqual(r['reason_code'],'energy_sufficient')
    def test_small_hold_gain_is_kept_for_peak_preservation(self):
        rows=series([.30,.31],loads=[1,1])
        r=self.decide(rows,params(initial_kwh=.5+1.192))
        self.assertEqual(r['reason_code'],'peak_hold')
        self.assertEqual(r['plan']['modes'],['hold','serve'])
        self.assertGreater(r['plan']['comparison']['hold_benefit_eur'],0)
        self.assertEqual(r['plan']['comparison']['incremental_grid_charge_benefit_eur'],0)
        self.assertFalse(r['normal_operation'])
    def test_carry_over_value_lets_cheap_charge_serve_a_later_day(self):
        # The price horizon ends with the last known Tibber interval. Without a
        # carry-over value any charge whose benefit lies on a later day is rejected.
        rows=series([.10,.10],loads=[.2,.2])
        p0=params(initial_kwh=.5,grid_charge_limit_kwh=4.5)
        r0=self.decide(rows,p0)
        self.assertNotIn('charge',r0['plan']['modes'])
        r1=self.decide(rows,replace(p0,terminal_value_eur_kwh=.24))
        self.assertEqual(r1['reason_code'],'economic_optimization')
        self.assertIn('charge',r1['plan']['modes'])
        self.assertGreater(r1['candidate_incremental_grid_charge_objective_eur'],.1)
        # Within-horizon cash savings stay negative on purpose: the value is carried over.
        self.assertLess(r1['plan']['comparison']['total_savings_eur'],0)
    def test_small_grid_charge_gain_is_still_rejected(self):
        rows=series([.30,.41],loads=[1,1])
        r=self.decide(rows)
        self.assertGreater(r['candidate_savings_eur'],0)
        self.assertLess(r['candidate_savings_eur'],.1)
        self.assertNotIn('charge',r['plan']['modes'])
        self.assertEqual(r['plan']['comparison']['incremental_grid_charge_benefit_eur'],0)
    def test_rejected_charge_does_not_discard_available_hold_plan(self):
        rows=series([.30,.41],loads=[1,2])
        r=self.decide(rows,params(initial_kwh=.5+1.192))
        self.assertGreater(r['candidate_savings_eur'],.1)
        self.assertEqual(r['reason_code'],'peak_hold')
        self.assertNotIn('charge',r['plan']['modes'])
        self.assertGreater(r['plan']['comparison']['hold_benefit_eur'],0)
        self.assertEqual(r['plan']['comparison']['incremental_grid_charge_benefit_eur'],0)
    def test_large_arbitrage_still_charges(self):
        rows=series([.1,1],loads=[1,1])
        r=self.decide(rows,params(grid_charge_limit_kwh=4.5))
        self.assertEqual(r['reason_code'],'economic_optimization')
        self.assertEqual(r['plan']['modes'],['charge','serve'])
    def test_margins_cannot_make_optimistic_summer_decision(self):
        rows=series([.2,.8],loads=[.3,.3],pvs=[0,.8])
        r=self.decide(rows,params(initial_kwh=.5),normal_pv_factor=.65,normal_load_factor=1.1,minimum_savings_eur=0)
        self.assertNotEqual(r['reason_code'],'energy_sufficient')
    def test_inverter_power_shortfall_is_not_mistaken_for_empty_battery(self):
        rows=series([.2,.9],loads=[5,5],pvs=[3,3])
        r=self.decide(rows,params(initial_kwh=2,max_discharge_kw=1))
        self.assertEqual(r['reason_code'],'energy_sufficient')
    def test_bad_policy_parameters_rejected(self):
        for cfg in [{'normal_pv_factor':1.1},{'normal_load_factor':.9},{'minimum_savings_eur':-.1}]:
            with self.subTest(cfg=cfg),self.assertRaises(ValueError):self.decide(series([.2]),**cfg)
if __name__=='__main__':unittest.main()
