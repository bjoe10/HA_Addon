"""Executable stdlib regression tests: python3.11 -m unittest -v."""
import dataclasses
import itertools
import json
import math
import random
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from optimizer import Interval, Params, optimize, schedules

UTC = timezone.utc
START = datetime(2026, 1, 5, tzinfo=UTC)


def series(prices, loads=None, pvs=None, start=START, minutes=60):
    loads = loads if loads is not None else [1.0] * len(prices)
    pvs = pvs if pvs is not None else [0.0] * len(prices)
    return [Interval(start + timedelta(minutes=i * minutes),
                     start + timedelta(minutes=(i + 1) * minutes), p, l, v)
            for i, (p, l, v) in enumerate(zip(prices, loads, pvs))]


def params(**kw):
    return Params(**(dict(capacity_kwh=5.0, reserve_kwh=0.5,
                         initial_kwh=0.5, max_discharge_kw=2.0,
                         pv_coupling='dc') | kw))


class OptimizerTests(unittest.TestCase):
    def assert_conservation(self, result, p):
        energy = p.initial_kwh
        for row in result['intervals']:
            self.assertAlmostEqual(row['initial_kwh'], energy)
            self.assertGreaterEqual(row['terminal_kwh'] + 1e-10, p.reserve_kwh)
            self.assertLessEqual(row['terminal_kwh'], p.capacity_kwh + 1e-10)
            self.assertAlmostEqual(row['grid_import_kwh'], row['house_grid_kwh'] + row['charger_ac_kwh'])
            self.assertAlmostEqual(row['load_kwh'], row['house_grid_kwh'] + row['served_ac_kwh'])
            self.assertAlmostEqual(row['terminal_kwh'] - energy,
                row['pv_kwh'] + row['charger_ac_kwh'] * p.charge_efficiency
                - row['served_ac_kwh'] / p.discharge_efficiency - row['spill_dc_kwh'])
            self.assertAlmostEqual(row['cost_eur'], row['grid_import_kwh'] * row['price_eur_kwh'])
            self.assertFalse(row['charger_ac_kwh'] > 0 and row['served_ac_kwh'] > 0)
            if row['mode'] == 'charge':
                self.assertAlmostEqual(row['charger_ac_kwh'], p.max_charge_kw * row['duration_hours'])
            energy = row['terminal_kwh']
        self.assertAlmostEqual(sum(x['cost_eur'] for x in result['intervals']), result['cost_eur'])
        self.assertAlmostEqual(energy, result['terminal_kwh'])

    def test_flat_prices_never_charge(self):
        r = optimize(series([0.3] * 6), params())
        self.assertNotIn('charge', r['modes'])
        self.assertAlmostEqual(r['cost_eur'], 1.8)
        self.assertEqual(r, optimize(series([0.3] * 6), params()))
        json.dumps(r, allow_nan=False)

    def test_cheap_now_expensive_later_roundtrip_loss(self):
        p = params()
        r = optimize(series([0.1, 1.0]), p)
        self.assertEqual(r['modes'], ['charge', 'serve'])
        self.assertAlmostEqual(p.charge_efficiency * p.discharge_efficiency, 0.75)
        self.assertAlmostEqual(r['intervals'][1]['served_ac_kwh'], 0.75)
        self.assertAlmostEqual(r['cost_eur'], 0.45)
        self.assert_conservation(r, p)

    def test_hold_preserves_energy_for_expensive_hour(self):
        p = params(initial_kwh=0.5 + 1.192)
        r = optimize(series([0.1, 1.0]), p)
        self.assertEqual(r['modes'], ['hold', 'serve'])
        self.assertGreater(r['comparison']['hold_benefit_eur'], 0)
        self.assertAlmostEqual(r['comparison']['incremental_grid_charge_benefit_eur'], 0)

    def test_no_gratuitous_last_hour_charge(self):
        r = optimize(series([0.01], loads=[0]), params())
        self.assertEqual(r['modes'], ['hold'])

    def test_negative_prices_import_is_real_and_bounded(self):
        p = params(capacity_kwh=0.6)
        r = optimize(series([-0.2], loads=[0.2]), p)
        self.assertEqual(r['modes'], ['charge'])
        self.assertAlmostEqual(r['cost_eur'], -0.24)
        self.assertGreater(r['intervals'][0]['spill_dc_kwh'], 0)
        self.assert_conservation(r, p)

    def test_pv_in_all_modes_and_headroom(self):
        p = params(capacity_kwh=1.5, initial_kwh=1.5)
        r = optimize(series([0.2, 0.01, 1], loads=[0.5, 0, 1], pvs=[0, 1, 0]), p)
        self.assertEqual(r['modes'][0], 'serve')
        self.assert_conservation(r, p)
        p2 = params()
        r2 = optimize(series([1], pvs=[1.192]), p2)
        self.assertAlmostEqual(r2['intervals'][0]['served_ac_kwh'], 1)
        self.assertAlmostEqual(r2['terminal_kwh'], p2.reserve_kwh)
        self.assert_conservation(r2, p2)
        r3 = optimize(series([0.2], loads=[0], pvs=[1]), p2)
        self.assertAlmostEqual(r3['terminal_kwh'], 1.5)

    def test_quarter_hour_charge_and_inverter_limit(self):
        p = params(initial_kwh=3, max_discharge_kw=0.4)
        r = optimize(series([1], minutes=15), p)
        self.assertAlmostEqual(r['intervals'][0]['served_ac_kwh'], 0.1)
        p = params()
        r = optimize(series([0.01, 1], minutes=15), p)
        self.assertAlmostEqual(r['intervals'][0]['charger_ac_kwh'], 0.25)
        self.assert_conservation(r, p)

    def test_substep_energy_is_not_lost_or_created(self):
        p = params(initial_kwh=0.53, energy_step_kwh=0.2)
        r = optimize(series([1] * 20, loads=[0.001] * 20), p)
        self.assertAlmostEqual(r['cost_eur'], 0)
        self.assert_conservation(r, p)

    def test_terminal_value_can_retain_inventory(self):
        p = params(terminal_value_eur_kwh=1)
        r = optimize(series([0.1], loads=[0]), p)
        self.assertEqual(r['modes'], ['charge'])
        self.assertAlmostEqual(r['objective_eur'], r['cost_eur'] - r['terminal_kwh'])

    def test_random_physical_replay_and_comparison(self):
        rng = random.Random(7)
        for _ in range(25):
            p = params(initial_kwh=rng.uniform(0.5, 5), energy_step_kwh=0.17)
            r = optimize(series([rng.uniform(-0.2, 1) for _ in range(12)],
                                [rng.random() for _ in range(12)],
                                [rng.random() for _ in range(12)], minutes=15), p)
            self.assert_conservation(r, p)
            c = r['comparison']
            self.assertLessEqual(r['cost_eur'], c['optimized_no_charge']['cost_eur'] + 1e-9)
            self.assertLessEqual(c['optimized_no_charge']['cost_eur'], c['serve_baseline']['cost_eur'] + 1e-9)
            self.assertAlmostEqual(c['hold_benefit_eur'], c['serve_baseline']['cost_eur'] - c['optimized_no_charge']['cost_eur'])
            self.assertAlmostEqual(c['incremental_grid_charge_benefit_eur'], c['optimized_no_charge']['cost_eur'] - r['cost_eur'])

    def test_exhaustive_small_grid_matches_independent_simulator(self):
        # All resulting inventories land exactly on .25-kWh grid nodes.
        # Independent exhaustive enumeration verifies the DP, not just its ledger.
        rng = random.Random(13)
        p = params(capacity_kwh=2, reserve_kwh=0, initial_kwh=1,
                   charge_efficiency=1, discharge_efficiency=0.75,
                   energy_step_kwh=0.25, max_discharge_kw=0.75)
        for _ in range(20):
            prices = [rng.choice([-0.2, 0, 0.1, 0.5, 1]) for _ in range(4)]
            loads = [rng.choice([0, 0.1875, 0.375, 0.75]) for _ in prices]
            pvs = [rng.choice([0, 0.25, 0.5]) for _ in prices]
            rows = series(prices, loads, pvs)
            best = math.inf
            best_no_charge = math.inf
            for modes in itertools.product(('hold', 'charge', 'serve'), repeat=4):
                energy, cost = 1, 0
                for price, load, pv, mode in zip(prices, loads, pvs, modes):
                    if mode == 'serve':
                        served = min(load, 0.75, (energy + pv) * 0.75)
                        energy = min(2, energy + pv - served / 0.75)
                        cost += (load - served) * price
                    else:
                        charger = 1 if mode == 'charge' else 0
                        energy = min(2, energy + pv + charger)
                        cost += (load + charger) * price
                best = min(best, cost)
                if 'charge' not in modes:
                    best_no_charge = min(best_no_charge, cost)
            result = optimize(rows, p)
            self.assertAlmostEqual(result['cost_eur'], best)
            self.assertAlmostEqual(result['comparison']['optimized_no_charge']['cost_eur'], best_no_charge)
            self.assert_conservation(result, p)

    def test_full_reserve_and_zero_inverter_remain_physical(self):
        p = params(capacity_kwh=0.5, initial_kwh=0.5, max_discharge_kw=0)
        result = optimize(series([1, 1], pvs=[2, 0]), p)
        self.assertAlmostEqual(result['cost_eur'], 2)
        self.assert_conservation(result, p)

    def test_pv_in_charge_mode_stores_without_serving_house(self):
        p = params()
        result = optimize(series([-1], loads=[1], pvs=[1]), p)
        flow = result['intervals'][0]
        self.assertEqual(flow['mode'], 'charge')
        self.assertAlmostEqual(flow['served_ac_kwh'], 0)
        self.assertAlmostEqual(flow['house_grid_kwh'], 1)
        self.assertAlmostEqual(flow['terminal_kwh'], 0.5 + 1 + p.charge_efficiency)
        self.assert_conservation(result, p)

    def test_invalid_params(self):
        for kw in [dict(capacity_kwh=0), dict(reserve_kwh=-1), dict(initial_kwh=6),
                   dict(max_charge_kw=0), dict(max_discharge_kw=-1), dict(energy_step_kwh=0),
                   dict(charge_efficiency=0), dict(discharge_efficiency=1.1),
                   dict(charge_efficiency=0.3), dict(pv_coupling='ac'),
                   dict(capacity_kwh=math.inf), dict(terminal_value_eur_kwh=-1)]:
            with self.subTest(kw=kw), self.assertRaises((ValueError, TypeError)):
                optimize(series([1]), params(**kw))

    def test_invalid_intervals(self):
        good = series([1, 2])
        bad = [[], [dataclasses.replace(good[0], load_kwh=-1)],
               [dataclasses.replace(good[0], pv_kwh=-1)],
               [dataclasses.replace(good[0], price_eur_kwh=math.nan)],
               [dataclasses.replace(good[0], start=START.replace(tzinfo=None))],
               [dataclasses.replace(good[0], end=START)], list(reversed(good)),
               [good[0], dataclasses.replace(good[1], start=good[1].start + timedelta(minutes=1))]]
        for rows in bad:
            with self.subTest(rows=rows), self.assertRaises((ValueError, TypeError)):
                optimize(rows, params())


class ScheduleTests(unittest.TestCase):
    def test_midnight_grouping_and_expiry(self):
        start = datetime(2026, 1, 5, 23, tzinfo=UTC)
        rows = series([1] * 4, start=start, minutes=30)
        expiry = rows[-1].end
        r = schedules(rows, ['charge'] * 4, expiry)
        self.assertEqual(set(r), {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'})
        self.assertEqual(r['mon'], [dict(start='23:00', end='24:00', mode='charge',
            data=dict(plan_date='2026-01-05', valid_until=expiry.isoformat()))])
        self.assertEqual(r['tue'][0]['start'], '00:00')
        self.assertEqual(r['tue'][0]['end'], '01:00')
        json.dumps(r)

    def test_dst_fall_active_ambiguous_rejected(self):
        zone = ZoneInfo('Europe/Berlin')
        for hour in [0, 1]:
            start = datetime(2026, 10, 25, hour, tzinfo=UTC)
            rows = [Interval(start.astimezone(zone), (start + timedelta(hours=1)).astimezone(zone), 1, 1, 0)]
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                schedules(rows, ['serve'], rows[-1].end)
            self.assertTrue(schedules(rows, ['hold'], rows[-1].end))
            self.assertTrue(optimize(rows, params()))

    def test_spring_forward_absolute_duration(self):
        zone = ZoneInfo('Europe/Berlin')
        start = datetime(2026, 3, 29, 1, tzinfo=zone)
        end = datetime(2026, 3, 29, 4, tzinfo=zone)
        rows = [Interval(start, end, 1, 3, 0)]
        r = optimize(rows, params(initial_kwh=4, max_discharge_kw=0.5))
        self.assertAlmostEqual(r['intervals'][0]['duration_hours'], 2)
        self.assertAlmostEqual(r['intervals'][0]['served_ac_kwh'], 1)
        self.assertEqual(schedules(rows, ['serve'], end)['sun'][0]['end'], '04:00')

    def test_schedule_invalid_input(self):
        rows = series([1])
        cases = [(rows, [], rows[-1].end), (rows, ['invalid'], rows[-1].end),
                 (rows, ['hold'], START.replace(tzinfo=None)),
                 (rows, ['serve'], START),
                 (series([1] * 8, minutes=1440), ['hold'] * 8, START + timedelta(days=8))]
        for args in cases:
            with self.subTest(args=args), self.assertRaises((ValueError, TypeError)):
                schedules(*args)


class SwitchCostTests(unittest.TestCase):
    def test_switch_cost_merges_equal_price_windows_without_changing_cash(self):
        from datetime import datetime,timedelta
        from zoneinfo import ZoneInfo
        from optimizer import Interval,Params,optimize
        tz=ZoneInfo('Europe/Berlin');start=datetime(2026,11,2,tzinfo=tz)
        prices=[.20,.20,.21,.20,.20,.21,.20,.20,.60,.60,.60,.60]
        rows=[Interval(start+timedelta(minutes=30*i),start+timedelta(minutes=30*i+30),p,.5 if p>.5 else .05,0.) for i,p in enumerate(prices)]
        base=Params(10,1,1,'dc',max_charge_kw=1,max_discharge_kw=2,energy_step_kwh=.05)
        free=optimize(rows,base)
        costly=optimize(rows,Params(**{**base.__dict__,'switch_cost_eur':.005}))
        switches=lambda m:sum(a!=b for a,b in zip(m,m[1:]))
        self.assertLessEqual(switches(costly['modes']),switches(free['modes']))
        self.assertLessEqual(costly['cost_eur'],free['cost_eur']+4*.005+1e-9)
        with self.assertRaises(ValueError):optimize(rows,Params(**{**base.__dict__,'switch_cost_eur':-1}))

if __name__ == '__main__':
    unittest.main()
