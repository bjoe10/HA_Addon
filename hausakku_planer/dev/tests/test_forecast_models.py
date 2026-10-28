"""Synthetic fixtures test causality/selection, not measured forecast accuracy."""
import copy
import json
import math
import unittest
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from forecast_models import evaluate_models, predict_load, predict_pv

TZ = ZoneInfo('Europe/Berlin')


def midnight(day):
    return datetime.combine(day, time(), TZ)


def dataset(days=150, start=date(2026, 1, 1), load=None, pv=None):
    hours, forecasts = [], []
    for i in range(days):
        day = start + timedelta(days=i)
        stamp, end = midnight(day).timestamp(), midnight(day + timedelta(days=1)).timestamp()
        slots = int((end - stamp) / 3600)
        for j in range(slots):
            dt = datetime.fromtimestamp(stamp + j * 3600, TZ)
            hours.append({'start': dt.timestamp(),
                          'load_kwh': load(i, dt) if load else 1.,
                          'pv_kwh': (pv(i) if pv else 8.) / slots})
        forecasts.append({'issued_at': datetime.combine(day - timedelta(days=1), time(20, 15), TZ).isoformat(),
                          'target_date': day.isoformat(), 'predicted_kwh': 4.})
    return {'hours': hours, 'pv_forecasts': forecasts,
            'cutoff': midnight(start + timedelta(days=days)).isoformat(), 'coverage': {}}


class ForecastModelTests(unittest.TestCase):
    def evaluate(self, data):
        return evaluate_models(data, datetime.fromisoformat(data['cutoff']) + timedelta(hours=20, minutes=15))

    def test_json_determinism_baseline_and_operational_calibration(self):
        data = dataset()
        artifact = self.evaluate(data)
        self.assertEqual(artifact, self.evaluate(copy.deepcopy(data)))
        artifact = json.loads(json.dumps(artifact, allow_nan=False))
        self.assertEqual(artifact['selected_model'], {'load': 'median28', 'pv': 'ratio28'})
        self.assertEqual(predict_load(artifact, datetime(2026, 6, 1, 12, tzinfo=TZ)), 1.)
        self.assertEqual(predict_pv(artifact, 4., '2026-06-01'), 8.)
        self.assertEqual(artifact['pv']['models']['ratio28']['pairs'], 28)
        self.assertEqual(artifact['backtest']['load']['kind'], 'historical_hindcast')
        self.assertEqual(artifact['backtest']['pv']['kind'], 'recorded_forecast_calibration_replay')

    def test_future_and_current_day_records_cannot_change_artifact(self):
        data = dataset(120)
        expected = self.evaluate(data)
        changed = copy.deepcopy(data)
        future = dataset(20, date.fromisoformat(data['cutoff'][:10]), load=lambda i, dt: 999., pv=lambda i: 999.)
        changed['hours'] += future['hours']
        changed['pv_forecasts'] += future['pv_forecasts']
        changed['coverage'] = {'untrusted_future_summary': 999}
        self.assertEqual(expected, self.evaluate(changed))

    def test_as_of_is_an_additional_cutoff(self):
        whole = dataset(140)
        shortened = dataset(100)
        issue = datetime.fromisoformat(shortened['cutoff']) + timedelta(hours=20)
        self.assertEqual(evaluate_models(whole, issue), evaluate_models(shortened, issue))

    def test_weekday_candidate_promoted_on_untouched_data(self):
        data = dataset(160, load=lambda i, dt: .2 + dt.weekday() * .6)
        artifact = self.evaluate(data)
        result = artifact['backtest']['load']
        self.assertEqual(artifact['selected_model']['load'], 'weekday56')
        self.assertTrue(result['promoted'])
        self.assertGreaterEqual(result['validation']['days'], 14)
        self.assertEqual(result['test']['days'], 14)
        self.assertLess(max(result['validation']['dates']), min(result['test']['dates']))
        self.assertGreaterEqual(result['test']['improvement_fraction'], .05)

    def test_candidate_selection_cannot_switch_after_test_rejection(self):
        # Training/validation have a weekly signal; the last fortnight loses it.
        data = dataset(160, load=lambda i, dt: (.2 + dt.weekday() * .6) if i < 146 else 2.)
        artifact = self.evaluate(data)
        result = artifact['backtest']['load']
        self.assertEqual(result['candidate'], 'weekday56')
        self.assertFalse(result['promoted'])
        self.assertEqual(artifact['selected_model']['load'], 'median28')
        self.assertIn('test', result['reason'])

    def test_sparse_pv_keeps_current_calibrated_baseline(self):
        data = dataset(120)
        data['pv_forecasts'] = data['pv_forecasts'][-10:]
        artifact = self.evaluate(data)
        self.assertEqual(artifact['selected_model']['pv'], 'ratio28')
        self.assertFalse(artifact['backtest']['pv']['promoted'])
        self.assertIn('insufficient', artifact['backtest']['pv']['reason'])
        self.assertEqual(predict_pv(artifact, 4., '2026-06-01'), 8.)

    def test_pv_recent_candidate_can_promote_with_sufficient_evidence(self):
        data = dataset(150, pv=lambda i: 4. + .1 * i)
        artifact = self.evaluate(data)
        self.assertEqual(artifact['selected_model']['pv'], 'ratio7')
        self.assertTrue(artifact['backtest']['pv']['promoted'])
        self.assertEqual(artifact['backtest']['pv']['test']['days'], 7)

    def test_target_day_or_late_evening_forecasts_are_not_training_pairs(self):
        data = dataset(90)
        expected = self.evaluate(data)
        for row in list(data['pv_forecasts']):
            target = date.fromisoformat(row['target_date'])
            data['pv_forecasts'].extend([
                dict(row, issued_at=datetime.combine(target, time(8), TZ).isoformat(), predicted_kwh=999.),
                dict(row, issued_at=datetime.combine(target - timedelta(days=1), time(20, 16), TZ).isoformat(), predicted_kwh=888.)])
        self.assertEqual(expected, self.evaluate(data))

    def test_dst_complete_days_accept_23_and_25_but_not_missing_hours(self):
        for start, expected_slots in [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)]:
            with self.subTest(day=start):
                data = dataset(1, start)
                self.assertEqual(len(data['hours']), expected_slots)
                artifact = self.evaluate(data)
                self.assertEqual(artifact['coverage']['complete_pv_days'], 1)
                self.assertEqual(artifact['coverage']['pv_pairs'], 1)
                data['hours'].pop(3)
                artifact = self.evaluate(data)
                self.assertEqual(artifact['coverage']['complete_pv_days'], 0)
                self.assertEqual(artifact['coverage']['pv_pairs'], 0)

    def test_missing_nonfinite_conflicting_data_do_not_become_zero(self):
        data = dataset(1)
        data['hours'][3]['load_kwh'] = None
        data['hours'][4]['pv_kwh'] = float('nan')
        data['hours'].append(dict(data['hours'][5], pv_kwh=100.))
        artifact = self.evaluate(data)
        json.dumps(artifact, allow_nan=False)
        self.assertEqual(artifact['coverage']['complete_pv_days'], 0)
        with self.assertRaises(ValueError):
            predict_load(artifact, datetime(2026, 1, 3, 3, tzinfo=TZ))
        self.assertTrue(math.isfinite(predict_pv(artifact, 1., '2026-01-03')))

    def test_three_group_samples_and_28_day_window_match_production(self):
        data = dataset(35, load=lambda i, dt: 100. if i < 7 else 1.)
        artifact = self.evaluate(data)
        self.assertEqual(predict_load(artifact, datetime(2026, 2, 6, 12, tzinfo=TZ)), 1.)
        sparse = dataset(3, date(2026, 1, 2), load=lambda i, dt: [1., 3., 5.][i])
        artifact = self.evaluate(sparse)
        # One Friday and two weekend samples: both groups must fall back to all.
        self.assertEqual(predict_load(artifact, datetime(2026, 1, 9, 12, tzinfo=TZ)), 3.)

    def test_aware_inputs_and_finite_predictions_are_enforced(self):
        data = dataset(4)
        with self.assertRaises(ValueError):
            evaluate_models(data, datetime(2026, 2, 1))
        artifact = self.evaluate(data)
        with self.assertRaises(ValueError):
            predict_load(artifact, datetime(2026, 2, 1))
        for raw in [float('nan'), float('inf'), -1.]:
            with self.assertRaises(ValueError):
                predict_pv(artifact, raw, '2026-02-01')
        with self.assertRaises(ValueError):
            predict_pv(artifact, 1., '2026-02-01', datetime(2025, 1, 1, tzinfo=TZ))
        with self.assertRaises(ValueError):
            predict_load(artifact, datetime(2025, 1, 1, tzinfo=TZ))

    def test_replay_excludes_issue_day_actuals_not_just_target_actuals(self):
        # First load origin has exactly 56 prior calendar days: only one label.
        data = dataset(58)
        original = self.evaluate(data)
        issue_day = date(2026, 1, 1) + timedelta(days=56)
        for row in data['hours']:
            if datetime.fromtimestamp(row['start'], TZ).date() == issue_day:
                row['load_kwh'] = 1000.
        changed = self.evaluate(data)
        self.assertEqual(original['backtest']['load'], changed['backtest']['load'])
        # Same check for the first PV replay after its 28-day warmup.
        data = dataset(30)
        original = self.evaluate(data)
        issue_day = date(2026, 1, 1) + timedelta(days=28)
        for row in data['hours']:
            if datetime.fromtimestamp(row['start'], TZ).date() == issue_day:
                row['pv_kwh'] = 1000.
        self.assertEqual(original['backtest']['pv'], self.evaluate(data)['backtest']['pv'])

    def test_empty_dataset_and_extreme_values_remain_json_finite(self):
        empty = {'hours': [], 'pv_forecasts': [], 'cutoff': '2026-03-01T00:00:00+01:00'}
        artifact = self.evaluate(empty)
        self.assertFalse(artifact['load']['available'])
        self.assertEqual(artifact['selected_model'], {'load': 'median28', 'pv': 'ratio28'})
        with self.assertRaises(ValueError):
            predict_load(artifact, datetime(2026, 3, 2, tzinfo=TZ))
        self.assertEqual(predict_pv(artifact, 0., '2026-03-02'), 0.)
        json.dumps(artifact, allow_nan=False)
        huge = dataset(100, load=lambda i, dt: 1e308, pv=lambda i: 1e308)
        artifact = self.evaluate(huge)
        json.dumps(artifact, allow_nan=False)
        self.assertTrue(math.isfinite(predict_load(artifact, datetime(2026, 6, 1, tzinfo=TZ))))
        with self.assertRaises(ValueError):
            predict_pv(artifact, 1e308, '2026-06-01')

    def test_stale_cutoff_does_not_shift_operational_28_day_window_backwards(self):
        data = dataset(30)
        artifact = evaluate_models(data, datetime(2026, 3, 15, 20, 15, tzinfo=TZ))
        self.assertFalse(artifact['load']['available'])
        self.assertEqual(artifact['pv']['models']['ratio28']['pairs'], 0)
        self.assertEqual(predict_pv(artifact, 4., '2026-03-16'), 4.)
        with self.assertRaises(ValueError):
            predict_load(artifact, datetime(2026, 3, 16, 12, tzinfo=TZ))

    def test_latest_eligible_forecast_is_used_and_conflicts_are_rejected(self):
        data = dataset(28)
        for row in list(data['pv_forecasts']):
            data['pv_forecasts'].append(dict(row, issued_at=row['issued_at'].replace('20:15:', '19:15:'), predicted_kwh=2.))
        artifact = self.evaluate(data)
        self.assertEqual(artifact['coverage']['pv_pairs'], 28)
        self.assertEqual(predict_pv(artifact, 4., '2026-02-01'), 8.)
        data['pv_forecasts'].append(dict(data['pv_forecasts'][0], predicted_kwh=3.))
        self.assertEqual(self.evaluate(data)['coverage']['pv_pairs'], 27)

    def test_holdout_labels_do_not_select_candidate(self):
        data = dataset(160, load=lambda i, dt: .2 + dt.weekday() * .6)
        original = self.evaluate(data)
        threshold = midnight(date(2026, 1, 1) + timedelta(days=146)).timestamp()
        for row in data['hours']:
            if row['start'] >= threshold:
                row['load_kwh'] = 99.
        changed = self.evaluate(data)
        self.assertEqual(original['backtest']['load']['candidate'], changed['backtest']['load']['candidate'])
        self.assertEqual(original['backtest']['load']['validation'], changed['backtest']['load']['validation'])


if __name__ == '__main__':
    unittest.main()
