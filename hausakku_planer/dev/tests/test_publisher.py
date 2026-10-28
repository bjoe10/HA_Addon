import unittest
from publisher import normalize_week, validate_schedule_pair

class PublisherTests(unittest.TestCase):
    def week(self):return {d:[] for d in ('monday','tuesday','wednesday','thursday','friday','saturday','sunday')}
    def test_normalizes_ha_end_of_day(self):
        a=self.week();a['sunday']=[{'from':'00:00','to':'24:00','data':{'plan_date':'2026-10-18'}}]
        b=self.week();b['sunday']=[{'from':'00:00:00','to':'23:59:59.999999','data':{'plan_date':'2026-10-18'}}]
        self.assertEqual(normalize_week(a),normalize_week(b))
    def test_rejects_overlaps_between_modes(self):
        a=self.week();b=self.week()
        a['sunday']=[{'from':'01:00','to':'02:00','data':{'plan_date':'2026-10-18'}}]
        b['sunday']=[{'from':'01:30','to':'03:00','data':{'plan_date':'2026-10-18'}}]
        with self.assertRaises(ValueError):validate_schedule_pair(a,b)
    def test_requires_date_binding(self):
        a=self.week();a['sunday']=[{'from':'01:00','to':'02:00'}]
        with self.assertRaises(ValueError):validate_schedule_pair(a,self.week())
    def test_requires_seven_explicit_days(self):
        with self.assertRaises(ValueError):validate_schedule_pair({},self.week())
if __name__=='__main__':unittest.main()
