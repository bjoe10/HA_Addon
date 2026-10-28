import unittest
from battery_calibration import calibrate,ENTITIES

def hours(rows):
    energy={k:{} for k in ENTITIES};voltage={}
    for t,(charger,bin_,bout,pv,wr,v) in enumerate(rows):
        for k,x in zip(('charger','battery_in','battery_out','pv','wr'),(charger,bin_,bout,pv,wr)):energy[k][t*3600.]=x
        voltage[t*3600.]=v
    return energy,voltage

class CalibrationTests(unittest.TestCase):
    def test_clean_hours_only_and_nominal_voltage_scale(self):
        rows=[(1.,.93,0,0,0,52.)]*10+[(0,0,.5,0,.42,51.)]*20+[(1.,1.5,0,.6,0,52.)]*5+[(0,0,.5,.3,.9,51.)]*5
        r=calibrate(*hours(rows))
        self.assertTrue(r['valid']);self.assertEqual((r['charge_hours'],r['discharge_hours']),(10,20))
        self.assertAlmostEqual(r['real_voltage_charge'],.93);self.assertAlmostEqual(r['charge_efficiency'],.93*51.2/52)
        self.assertAlmostEqual(r['discharge_efficiency'],.84*51/51.2);self.assertAlmostEqual(r['roundtrip'],.93*.84*51/52)
    def test_nominal_voltage_is_configurable(self):
        rows=[(1.,.93,0,0,0,52.)]*10+[(0,0,.5,0,.42,51.)]*20
        r=calibrate(*hours(rows),nominal_voltage=48.)
        self.assertAlmostEqual(r['charge_efficiency'],.93*48/52);self.assertAlmostEqual(r['discharge_efficiency'],.84*51/48)
    def test_without_nominal_voltage_the_measured_ratio_is_used_unscaled(self):
        rows=[(1.,.93,0,0,0,52.)]*10+[(0,0,.5,0,.42,51.)]*20
        r=calibrate(*hours(rows),nominal_voltage=None)
        self.assertAlmostEqual(r['charge_efficiency'],.93);self.assertAlmostEqual(r['discharge_efficiency'],.84)
    def test_too_few_or_implausible_measurements_are_not_used(self):
        few=calibrate(*hours([(1.,.93,0,0,0,52.)]*3+[(0,0,.5,0,.42,51.)]*20))
        self.assertFalse(few['valid']);self.assertIn('zu wenige',few['reason'])
        odd=calibrate(*hours([(1.,1.4,0,0,0,51.2)]*10+[(0,0,.5,0,.42,51.2)]*20))
        self.assertFalse(odd['valid']);self.assertIn('plausibler',odd['reason'])
        self.assertFalse(calibrate({},{})['valid'])

if __name__=='__main__':unittest.main()
