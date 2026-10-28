import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from collector import normalize_statistics, historical_forecasts, join_balances

class CollectorTests(unittest.TestCase):
    def test_confirmed_car_meter_is_cee_ac_energy(self):
        import collector
        self.assertEqual(collector.vehicle_entities(),['sensor.cee_energy','sensor.second_ev_energy'])
    def test_stats_convert_units(self):
        d={'data':{'entities':[{'entity_id':'sensor.a','unit_of_measurement':'Wh','has_more':False,'statistics':[{'start':100000,'change':2000}]}]}}
        self.assertEqual(normalize_statistics(d)['sensor.a'][100.],2.)
    def test_stats_refuse_truncation(self):
        d={'data':{'entities':[{'entity_id':'sensor.a','unit_of_measurement':'Wh','has_more':True,'statistics':[]}]}}
        with self.assertRaises(ValueError): normalize_statistics(d)
    def test_forecasts_paired_with_next_day_not_same_day(self):
        d={'data':{'entities':[{'states':[{'state':'1.2','last_updated':'2026-10-16T20:00:00+02:00'}, {'state':'1.4','last_updated':'2026-10-16T22:00:00+02:00'}],'has_more':False}]}}
        self.assertEqual(historical_forecasts(d),{'2026-10-17':1.2})
    def test_forecasts_do_not_peek_after_daily_decision_time(self):
        d={'data':{'entities':[{'states':[{'state':'2','last_updated':'2026-10-16T20:15:00+02:00'}, {'state':'9','last_updated':'2026-10-16T20:15:01+02:00'}],'has_more':False}]}}
        self.assertEqual(historical_forecasts(d),{'2026-10-17':2.0})
    def test_forecasts_without_timezone_are_not_assumed_observable(self):
        d={'data':{'entities':[{'states':[{'state':'9','last_updated':'2026-10-16T20:00:00'}],'has_more':False}]}}
        self.assertEqual(historical_forecasts(d),{})
    def test_balances_require_complete_energy_rows(self):
        data={'g':{1.:1},'w':{1.:.4},'c':{1.:.1},'e':{1.:0},'v':{1.:0}}
        rows=join_balances(data,dict(grid='g',wr='w',charger='c',export='e',ev='v'))
        self.assertEqual(rows[0]['wr'],.4)
        del data['w'][1.]
        self.assertEqual(join_balances(data,dict(grid='g',wr='w',charger='c',export='e',ev='v')),[])
if __name__=='__main__': unittest.main()
