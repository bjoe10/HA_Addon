"""Deterministic, standard-library, leakage-safe forecast comparison.

Public API
==========
evaluate_models(annual_dataset, as_of: aware datetime) -> JSON-safe dict
    Input: {'hours': [{'start': Unix seconds, 'load_kwh': number|None,
    'pv_kwh': number|None}], 'pv_forecasts': [{'issued_at': offset ISO,
    'target_date': 'YYYY-MM-DD', 'predicted_kwh': number}], 'cutoff': offset
    ISO local midnight, 'coverage': {...}}. Coverage metadata is not trusted.
    Data are restricted to completed Europe/Berlin days before BOTH cutoff and
    as_of's local day. Repeated DST hours are separate elapsed-hour observations.
    None/negative/nonfinite measurements are missing, never imputed as zero;
    conflicting duplicate values invalidate that channel's hour.

predict_load(artifact, start: aware datetime) -> hourly kWh
    One elapsed hour, NOT kW or quarter-hour energy. Repeated autumn hours share
    a wall-clock profile. Missing training-hour coverage raises ValueError.

predict_pv(artifact, raw_forecast_kwh, target_date: str|date,
           issued_at: aware datetime|offset ISO|None = None) -> daily kWh
    Apply a calibration to a real weather forecast; this is not a weather model.
    None uses artifact's as_of. Reusing an artifact before its as_of is rejected.
    Target must be a future local day relative to the forecast issue.

Artifact includes selected_model {'load': ..., 'pv': ...}, both baseline flags,
all final fitted models, coverage, and backtest validation/test metrics and dates.
It survives json.dumps(..., allow_nan=False) / json.loads without custom codecs.

Protocol (fixed before seeing data)
==================================
Operational load baseline: preceding 28 calendar days, hourly median, weekday /
weekend groups only with >=3 hourly observations; otherwise all-day median.
Candidates: analogous 7-day profile, and a 56-day exact-weekday median (>=4
samples) shrunk 25% toward the baseline. No neural weights or optional packages.
PV baseline: median actual/raw ratios in preceding 28 calendar days, >=3 pairs,
otherwise factor 1. Candidate: last 7 calendar days (>=3), else baseline factor.
Operational windows are anchored to as_of, not shifted back to a stale cutoff.
Only raw PV forecasts >=0.2 kWh enter ratio calibration or its replay metrics.
Only the latest preceding-day forecast issued at/before 20:15 Berlin is paired;
forecasts from target day, after 20:15, or other issue days are excluded. Complete
23/24/25-hour actual days are required. No historical forecast is invented.

Replay uses issue D-1 at 20:15 to predict D: D-1 actuals are NOT available even
though they appear in a later archive. Load replay starts after 56 calendar days
of history, PV after 28, and requires a covered baseline / >=3 prior PV pairs.
Last 14 load days / 7 PV pairs are an untouched chronological test; preceding
up-to-28 evaluation days form validation (min 14 load / 7 PV). Choose ONE
candidate on validation MAE only, then require >=5% paired MAE improvement on
BOTH validation and test, with no >5% tail worsening, alarming bias, or increased
overprediction. Test rejection never triggers selection of another candidate.
Rolling refits may use earlier test-day actuals once observable; candidate
selection does not. Final models refit through the operational cutoff regardless
of promotion. Sparse evidence always retains the current corrected baseline.

Load metrics equally weight complete local target days (hourly errors within
each day); PV metrics are daily errors. p90 is nearest-rank daily MAE. These are
historical load hindcasts / recorded PV calibration replays, not prospective
accuracy claims or guaranteed improvement. Hour records lack publication times:
we assume completed-day measurements were observable on the following day;
backfills/revisions cannot be audited without original measurement vintages.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import math

TZ = ZoneInfo('Europe/Berlin')
LOAD_BASELINE = 'median28'
PV_BASELINE = 'ratio28'
LOAD_CANDIDATES = ('median7', 'weekday56')
PV_CANDIDATES = ('ratio7',)


def _aware(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone-aware datetime required')
    return value.astimezone(TZ)


def _midnight(day):
    return datetime.combine(day, time(), TZ)


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _median(values):
    if not values:
        return None
    v = sorted(values)
    n = len(v)
    return v[n // 2] if n % 2 else v[n // 2 - 1] + (v[n // 2] - v[n // 2 - 1]) / 2


def _mean(values):
    return math.fsum(v / len(values) for v in values)


def _prepare(dataset, boundary):
    # Values are channel-independent; an invalid PV reading must not erase load.
    buckets = {}
    for row in dataset.get('hours', []):
        try:
            stamp = float(row['start'])
            dt = datetime.fromtimestamp(stamp, TZ)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if dt.date() >= boundary or dt.minute or dt.second or dt.microsecond:
            continue
        day = buckets.setdefault(dt.date(), {})
        values = (_number(row.get('load_kwh')), _number(row.get('pv_kwh')))
        if stamp not in day:
            day[stamp] = values
        else:
            day[stamp] = tuple(a if a == b else None for a, b in zip(day[stamp], values))
    complete = {'load': {}, 'pv': {}}
    for day, rows in buckets.items():
        lo, hi = _midnight(day).timestamp(), _midnight(day + timedelta(days=1)).timestamp()
        expected = set(range(int(lo), int(hi), 3600))
        if set(rows) != expected:
            continue
        for channel, index in [('load', 0), ('pv', 1)]:
            if all(values[index] is not None for values in rows.values()):
                complete[channel][day] = [(stamp, rows[stamp][index]) for stamp in sorted(rows)]
    records = {}
    conflicts = set()
    for row in dataset.get('pv_forecasts', []):
        try:
            target = date.fromisoformat(row['target_date'])
            issued = _aware(row['issued_at'])
            raw = _number(row.get('predicted_kwh'))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if target >= boundary or target not in complete['pv'] or raw is None or raw < .2:
            continue
        if issued.date() != target - timedelta(days=1) or issued.time().replace(tzinfo=None) > time(20, 15):
            continue
        key = (target, issued.timestamp())
        if key in records and records[key] != raw:
            conflicts.add(key)
        records[key] = raw
    # Conflicting issue vintages invalidate that target, not silently an older one.
    conflicting_targets = {key[0] for key in conflicts}
    pairs = {}
    for (target, stamp), raw in sorted(records.items()):
        if target in conflicting_targets:
            continue
        try:
            actual = math.fsum(v for _, v in complete['pv'][target])
        except OverflowError:
            continue
        ratio = actual / raw
        if math.isfinite(ratio):
            pairs[target] = {'raw': raw, 'actual': actual, 'ratio': ratio,
                             'issued_at': datetime.fromtimestamp(stamp, TZ).isoformat()}
    return buckets, complete, pairs


def _profile(buckets, before, window):
    groups = {key: [[] for _ in range(24)] for key in ('all', 'weekday', 'weekend')}
    weekdays = [[[] for _ in range(24)] for _ in range(7)]
    for day in sorted(buckets):
        if not before - timedelta(days=window) <= day < before:
            continue
        group = 'weekend' if day.weekday() >= 5 else 'weekday'
        for stamp, (load, _) in sorted(buckets[day].items()):
            if load is None:
                continue
            hour = datetime.fromtimestamp(stamp, TZ).hour
            groups['all'][hour].append(load)
            groups[group][hour].append(load)
            weekdays[day.weekday()][hour].append(load)
    values = []
    for wd in range(7):
        group = groups['weekend' if wd >= 5 else 'weekday']
        values.append([_median(group[h] if len(group[h]) >= 3 else groups['all'][h]) for h in range(24)])
    return {'values': values, 'window_days': window,
            'samples': {key: [len(v) for v in hours] for key, hours in groups.items()}}, weekdays


def _fit_load(buckets, before):
    baseline, _ = _profile(buckets, before, 28)
    recent, _ = _profile(buckets, before, 7)
    _, weekdays = _profile(buckets, before, 56)
    specific = []
    for wd in range(7):
        values = []
        for h in range(24):
            base = baseline['values'][wd][h]
            hist = weekdays[wd][h]
            value = (.75 * _median(hist) + .25 * base) if len(hist) >= 4 and base is not None else base
            values.append(value)
        specific.append(values)
    # Candidate absence cannot erase a usable baseline hour.
    for wd in range(7):
        for h in range(24):
            if recent['values'][wd][h] is None:
                recent['values'][wd][h] = baseline['values'][wd][h]
    return {LOAD_BASELINE: baseline, 'median7': recent,
            'weekday56': {'values': specific, 'window_days': 56, 'baseline_shrinkage': .25}}


def _fit_pv(pairs, before):
    def ratios(window):
        return [pairs[d]['ratio'] for d in sorted(pairs) if before - timedelta(days=window) <= d < before]
    values28, values7 = ratios(28), ratios(7)
    base = _median(values28) if len(values28) >= 3 else 1.
    return {PV_BASELINE: {'factor': base, 'pairs': len(values28), 'window_days': 28},
            'ratio7': {'factor': _median(values7) if len(values7) >= 3 else base,
                       'pairs': len(values7), 'window_days': 7}}


def _errors(actual, predicted):
    residuals = [p - a for a, p in zip(actual, predicted)]
    return {'mae': _mean([abs(r) for r in residuals]), 'bias': _mean(residuals),
            'overprediction': _mean([max(0., r) for r in residuals])}


def _metrics(rows, model):
    values = [row['errors'][model] for row in rows]
    if not values:
        return {'mae': None, 'bias': None, 'overprediction': None, 'p90_daily_mae': None}
    tail = sorted(v['mae'] for v in values)[math.ceil(.9 * len(values)) - 1]
    return dict({key: _mean([v[key] for v in values]) for key in ('mae', 'bias', 'overprediction')},
                p90_daily_mae=tail)


def _assessment(rows, baseline, candidate):
    b, c = _metrics(rows, baseline), _metrics(rows, candidate)
    improvement = (b['mae'] - c['mae']) / b['mae'] if b['mae'] not in (None, 0.) else 0.
    return {'days': len(rows), 'dates': [row['date'] for row in rows],
            'baseline': b, 'candidate': c, 'improvement_fraction': improvement}


def _passes(assessment):
    b, c = assessment['baseline'], assessment['candidate']
    if b['mae'] is None or b['mae'] <= 0 or assessment['improvement_fraction'] < .05:
        return False
    slack = 1e-12
    return (c['p90_daily_mae'] <= b['p90_daily_mae'] * 1.05 + slack
            and abs(c['bias']) <= abs(b['bias']) + .1 * b['mae'] + slack
            and c['overprediction'] <= b['overprediction'] * 1.05 + .05 * b['mae'] + slack)


def _compare(rows, baseline, candidates, minimum_validation, test_days, kind, unit):
    test = rows[-test_days:]
    validation = rows[max(0, len(rows) - test_days - 28):max(0, len(rows) - test_days)]
    # This choice reads validation only, including when the test later fails.
    chosen = min(candidates, key=lambda m: (_metrics(validation, m)['mae']
                                          if validation else float('inf'), m))
    val = _assessment(validation, baseline, chosen)
    heldout = _assessment(test, baseline, chosen)
    enough = len(validation) >= minimum_validation and len(test) >= test_days
    if not enough:
        reason = 'insufficient independent validation/test days; retain corrected baseline'
    elif not _passes(val):
        reason = 'validation improvement or bias/overprediction/tail safeguards failed'
    elif not _passes(heldout):
        reason = 'untouched test improvement or bias/overprediction/tail safeguards failed'
    else:
        reason = 'paired validation and untouched test passed fixed promotion safeguards'
    promoted = enough and _passes(val) and _passes(heldout)
    return {'kind': kind, 'metric_unit': unit, 'candidate': chosen, 'promoted': promoted,
            'reason': reason, 'validation': val, 'test': heldout,
            'validation_candidates': {m: _metrics(validation, m) for m in candidates},
            'minimum_validation_days': minimum_validation, 'minimum_test_days': test_days,
            'minimum_improvement_fraction': .05}, chosen if promoted else baseline


def evaluate_models(annual_dataset, as_of):
    """Fit operational profiles and compare fixed candidates (see module contract)."""
    issue = _aware(as_of)
    cutoff = _aware(annual_dataset['cutoff'])
    if cutoff.time().replace(tzinfo=None) != time():
        raise ValueError('Dataset cutoff must be Europe/Berlin local midnight')
    boundary = min(issue.date(), cutoff.date())
    buckets, complete, pairs = _prepare(annual_dataset, boundary)
    first = min(buckets) if buckets else boundary
    load_rows, pv_rows = [], []
    for target in sorted(complete['load']):
        before = target - timedelta(days=1)
        if (before - first).days < 56:
            continue
        models = _fit_load(buckets, before)
        actual = [v for _, v in complete['load'][target]]
        errors = {}
        for name, model in models.items():
            predicted = [model['values'][target.weekday()][datetime.fromtimestamp(stamp, TZ).hour]
                         for stamp, _ in complete['load'][target]]
            if any(v is None for v in predicted):
                break
            errors[name] = _errors(actual, predicted)
        if len(errors) == len(models):
            load_rows.append({'date': target.isoformat(), 'errors': errors})
    for target in sorted(pairs):
        before = target - timedelta(days=1)
        if (before - first).days < 28:
            continue
        models = _fit_pv(pairs, before)
        if models[PV_BASELINE]['pairs'] < 3:
            continue
        actual, raw = pairs[target]['actual'], pairs[target]['raw']
        errors = {}
        for name, model in models.items():
            predicted = raw * model['factor']
            if not math.isfinite(predicted):
                break
            errors[name] = _errors([actual], [predicted])
        if len(errors) == len(models):
            pv_rows.append({'date': target.isoformat(), 'errors': errors})
    load_test, load_selected = _compare(load_rows, LOAD_BASELINE, LOAD_CANDIDATES, 14, 14,
                                        'historical_hindcast', 'kWh/hour')
    pv_test, pv_selected = _compare(pv_rows, PV_BASELINE, PV_CANDIDATES, 7, 7,
                                    'recorded_forecast_calibration_replay', 'kWh/day')
    # Availability limits training observations, but must not move rolling
    # operational windows backwards when a caller supplies an old archive.
    load_models, pv_models = _fit_load(buckets, issue.date()), _fit_pv(pairs, issue.date())
    return {'schema_version': 1, 'timezone': 'Europe/Berlin', 'as_of': issue.isoformat(),
            'trained_before': _midnight(boundary).isoformat(),
            'selected_model': {'load': load_selected, 'pv': pv_selected},
            'load': {'selected_model': load_selected, 'baseline_model': LOAD_BASELINE,
                     'is_baseline': load_selected == LOAD_BASELINE,
                     'available': all(v is not None for values in load_models[load_selected]['values'] for v in values),
                     'models': load_models},
            'pv': {'selected_model': pv_selected, 'baseline_model': PV_BASELINE,
                   'is_baseline': pv_selected == PV_BASELINE, 'models': pv_models},
            'coverage': {'hour_records': sum(len(rows) for rows in buckets.values()),
                         'complete_load_days': len(complete['load']), 'complete_pv_days': len(complete['pv']),
                         'pv_pairs': len(pairs), 'load_evaluation_days': len(load_rows),
                         'pv_evaluation_days': len(pv_rows)},
            'backtest': {'load': load_test, 'pv': pv_test},
            'limitations': ['Load results are historical hindcasts, not recorded predictions.',
                            'PV replay needs genuinely recorded preceding-evening forecasts.',
                            'Completed-day measurements are assumed available the next day; revision vintages unknown.',
                            'Promotion does not guarantee future improvement.']}


def predict_load(artifact, start):
    """Return expected energy for an elapsed hour; reject missing/backcast inputs."""
    start = _aware(start)
    if start.date() < _aware(artifact['as_of']).date():
        raise ValueError('Artifact cannot be used to predict a past local day')
    model = artifact['load']['models'][artifact['selected_model']['load']]
    value = _number(model['values'][start.weekday()][start.hour])
    if value is None:
        raise ValueError('Missing historical observations for this load hour')
    return value


def predict_pv(artifact, raw_forecast_kwh, target_date, issued_at=None):
    """Return corrected genuine raw daily forecast; does not reconstruct weather."""
    raw = _number(raw_forecast_kwh)
    if raw is None:
        raise ValueError('PV forecast must be finite and nonnegative')
    issue = _aware(issued_at if issued_at is not None else artifact['as_of'])
    if issue.timestamp() < _aware(artifact['as_of']).timestamp():
        raise ValueError('Artifact contains observations unavailable at requested issue time')
    target = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
    if isinstance(target, datetime) or not isinstance(target, date) or target <= issue.date():
        raise ValueError('PV target must be a future local day after issue')
    factor = _number(artifact['pv']['models'][artifact['selected_model']['pv']]['factor'])
    if factor is None or not math.isfinite(raw * factor):
        raise ValueError('PV calibration produced nonfinite energy')
    return raw * factor
