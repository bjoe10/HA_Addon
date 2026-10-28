import unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from planner_data import prepare

class PrepareTests(unittest.TestCase):
    def fixture(self):
        tz=ZoneInfo('Europe/Berlin'); t=datetime(2026,10,17,23,45,tzinfo=tz)
        rows=[]
        for i in range(96):
            rows.append({'start_time':(t+timedelta(minutes=15*i)).isoformat(),'price':.3})
        balances=[]
        for i in range(24*4):
            balances.append({'start':(t.replace(hour=0,minute=0)-timedelta(hours=i+1)).timestamp(),'grid':.3,'wr':.1,'charger':0,'export':0,'ev':0})
        return {'planning_start':t.isoformat(),'prices':rows,'balances':balances,
         'states':{'sensor.hausbatterie_kwh':{'state':'6'},'sensor.ant_bms_16_soc':{'state':'40'},
         'sensor.energy_production_tomorrow':{'state':'1'},'sensor.energy_production_today_remaining':{'state':'0'}},
         'pv_actual_by_day':{},'pv_predicted_by_day':{},'pv_shape_samples':[[1] if 8<=h<=16 else [0] for h in range(24)]}
    def test_energy_units_and_capacity_inference(self):
        d=prepare(self.fixture(),{'capacity_kwh':None,'reserve_fraction':.1,'upper_soc_fraction':.9,'minimum_group_samples':3})
        self.assertEqual(d['nominal_capacity_kwh'],15)
        self.assertAlmostEqual(d['intervals'][0]['load_kwh'],.1)
        self.assertTrue(d['capacity_inferred'])
    def test_pv_conservation(self):
        d=prepare(self.fixture(),{'capacity_kwh':15,'reserve_fraction':.1,'upper_soc_fraction':.9,'minimum_group_samples':3})
        self.assertAlmostEqual(sum(i['pv_kwh'] for i in d['intervals']),1)
    def test_physical_capacity_is_separate_from_grid_ceiling(self):
        d=prepare(self.fixture(),{'capacity_kwh':15,'reserve_fraction':.1,'grid_charge_max_soc_fraction':.9})
        self.assertEqual(d['planning_capacity_kwh'],15)
        self.assertEqual(d['grid_charge_limit_kwh'],13.5)
    def test_empty_battery_with_known_capacity_is_valid(self):
        x=self.fixture();x['states']['sensor.hausbatterie_kwh']['state']='0';x['states']['sensor.ant_bms_16_soc']['state']='0'
        self.assertEqual(prepare(x,{'capacity_kwh':15})['initial_kwh'],0)
    def test_invalid_boundary_fractions_fail(self):
        for reserve,cap in [(-.1,.9),(.9,.8),(.1,1.1)]:
            with self.subTest(reserve=reserve,cap=cap),self.assertRaises(ValueError):
                prepare(self.fixture(),{'capacity_kwh':15,'reserve_fraction':reserve,'grid_charge_max_soc_fraction':cap})
    def test_missing_soc_does_not_invent_capacity(self):
        x=self.fixture();x['states']['sensor.ant_bms_16_soc']['state']='unavailable'
        with self.assertRaises(ValueError):prepare(x,{'capacity_kwh':None})
if __name__=='__main__':unittest.main()
