"""Regression: a depleted battery must not lower the configured reserve."""
import json
import unittest
from pathlib import Path
from optimizer import optimize, Params
from test_optimizer import series, params
from planner import compute_plan

class LowInitialReserveTests(unittest.TestCase):
    def test_below_reserve_is_valid_without_creating_energy(self):
        p=params(initial_kwh=0.2,reserve_kwh=0.5)
        r=optimize(series([1,1],pvs=[0,0]),p)
        self.assertEqual(r['params']['reserve_kwh'],0.5)
        self.assertAlmostEqual(r['terminal_kwh'],0.2)
        self.assertTrue(all(f['served_ac_kwh']==0 for f in r['intervals']))

    def test_grid_charge_can_recover_above_unchanged_reserve(self):
        p=params(initial_kwh=0.2,reserve_kwh=0.5)
        r=optimize(series([0.01,1]),p)
        self.assertEqual(r['modes'],['charge','serve'])
        self.assertAlmostEqual(r['terminal_kwh'],p.reserve_kwh)
        self.assertAlmostEqual(r['intervals'][1]['served_ac_kwh'],(0.2+p.charge_efficiency-0.5)*p.discharge_efficiency)

    def test_pv_recovery_preserves_original_reserve(self):
        p=params(initial_kwh=0.2,reserve_kwh=0.5)
        r=optimize(series([0.8,1],loads=[0,1],pvs=[0.6,0]),p)
        self.assertAlmostEqual(r['terminal_kwh'],0.5)
        self.assertLessEqual(r['intervals'][1]['battery_discharge_dc_kwh'],0.3+1e-9)

    def test_planner_does_not_clamp_reserve_to_initial_energy(self):
        root=Path(__file__).parent
        s=json.loads((root/'fixtures/test_fixture_snapshot.json').read_text())
        c=json.loads((root.parent/'tests/fixtures/config_legacy.json').read_text())
        s['states']['sensor.hausbatterie_kwh']['state']='0.7'
        s['states']['sensor.ant_bms_16_soc']['state']='5'
        r=compute_plan(s,c)
        reserve=c['capacity_kwh']*c['reserve_fraction']
        self.assertAlmostEqual(r['plan']['params']['reserve_kwh'],reserve)
        self.assertAlmostEqual(r['plan']['initial_kwh'],0.7)
        for f in r['plan']['intervals']:
            self.assertLessEqual(f['battery_discharge_dc_kwh'],max(0,f['initial_kwh']-reserve)+1e-9)

if __name__=='__main__':unittest.main()
