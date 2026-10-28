import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from forecast import energy_kwh, load_profile, pv_calibration, price_intervals

TZ = ZoneInfo('Europe/Berlin')

class ForecastTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(energy_kwh(1500, 'Wh'), 1.5)
        self.assertEqual(energy_kwh(1.5, 'kWh'), 1.5)
        with self.assertRaises(ValueError): energy_kwh(1, 'W')

    def test_balance_includes_inverter_excludes_charger_and_exports(self):
        t = datetime(2026,10,1,12,tzinfo=TZ).timestamp()
        rows = [{'start':t,'grid':1.,'wr':.5,'charger':.2,'export':.1,'ev':.3}]
        p = load_profile(rows)
        self.assertAlmostEqual(p['all'][12], .9)

    def test_missing_measurement_is_not_zero(self):
        with self.assertRaises(ValueError): load_profile([{'start':0,'grid':1}])

    def test_robust_profile_uses_median(self):
        base = datetime(2026,10,1,12,tzinfo=TZ)
        rows = [{'start':(base+timedelta(days=i)).timestamp(),'grid':v,'wr':0,'charger':0,'export':0,'ev':0} for i,v in enumerate([1,1,20])]
        self.assertEqual(load_profile(rows)['all'][12], 1)

    def test_pv_calibration_uses_only_completed_paired_days(self):
        p = pv_calibration({'2026-10-01':4,'2026-10-02':6,'2026-10-03':20},
                           {'2026-10-01':1,'2026-10-02':2}, '2026-10-03')
        self.assertEqual(p['pairs'], 2)
        self.assertEqual(p['factor'], 3.5)

    def test_calibration_does_not_invent_evidence(self):
        self.assertEqual(pv_calibration({}, {}, '2026-10-03'), {'factor':1.,'pairs':0,'ratios':[]})

    def test_prices_validate_gaps(self):
        rows = [{'start_time':'2026-10-18T00:00:00+02:00','price':.3},
                {'start_time':'2026-10-18T00:30:00+02:00','price':.4}]
        with self.assertRaises(ValueError): price_intervals(rows,datetime(2026,10,18,0,tzinfo=TZ))

    def test_prices_negative_and_clipped_first(self):
        rows=[{'start_time':'2026-10-18T00:00:00+02:00','price':-.1},
              {'start_time':'2026-10-18T00:15:00+02:00','price':.2}]
        out=price_intervals(rows,datetime(2026,10,18,0,5,tzinfo=TZ))
        self.assertEqual(out[0]['start'].minute,5)
        self.assertEqual(out[0]['price_eur_kwh'],-.1)
        self.assertEqual(len(out),2)

class EstimatorTests(unittest.TestCase):
    def test_weighted_mean_prefers_recent_days_and_median_ignores_outliers(self):
        from forecast import estimate
        samples=[(1.,0.),(3.,7.),(10.,70.)]
        self.assertEqual(estimate(samples),3.)
        w=estimate(samples,'weighted_mean',7.)
        self.assertAlmostEqual(w,(1+3*.5+10*.5**10)/(1+.5+.5**10))
        self.assertIsNone(estimate([]))
        with self.assertRaises(ValueError):estimate(samples,'mode')
    def test_load_profile_weighted_by_age(self):
        from datetime import datetime,timedelta
        from forecast import load_profile,TZ
        now=datetime(2026,10,25,12,tzinfo=TZ)
        rows=[{'start':(now-timedelta(days=d)).timestamp(),'grid':v,'wr':0,'charger':0,'export':0,'ev':0} for d,v in ((1,2.),(8,1.),(15,1.))]
        self.assertEqual(load_profile(rows)['all'][12],1.)
        weighted=load_profile(rows,'weighted_mean',7.,now)['all'][12]
        self.assertGreater(weighted,1.5);self.assertLess(weighted,2.)

if __name__ == '__main__': unittest.main()
