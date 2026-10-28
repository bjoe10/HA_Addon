"""Deterministic, dependency-free DC-coupled home battery planning (Python 3.11+).

Public API::
    optimize(intervals: Sequence[Interval], params: Params) -> dict
    schedules(intervals: Sequence[Interval], modes: Sequence[str],
              valid_until: datetime) -> dict[str, list[dict]]

All battery/PV energies are DC kWh; house/charger/inverter output are AC kWh.
The caller MUST explicitly confirm pv_coupling='dc'. max_discharge_kw is the
AC inverter output limit (including direct PV). With explicit
grid_charge_limit_kwh, charger runs at max_charge_kw only until its separate
ceiling, while PV may fill physical capacity above it. PV has priority.
The legacy default None retains fixed full-interval draw/spill for backwards
compatibility; the actual planner ALWAYS supplies an explicit ceiling.
Optional decision_block_minutes groups consecutive intervals into a common
mode, but replays their physical flows individually and chronologically.
No export revenue, wear, self-discharge, standby power or intra-interval timing
is modeled. Interval totals assume PV and load can be balanced in that interval.

Approximation: backward dynamic programming samples battery inventory on a
regular grid (plus exact capacity) and linearly interpolates future value.
It DOES NOT round physical battery energy per interval. Forward replay chooses
feasible actions at the actual continuous inventory and reports only real
replayed flows. Thus interpolation can affect optimality, never manufacture
energy. Smaller energy_step_kwh generally improves accuracy; there is no global
optimality/error-bound claim. Both the continuous-serve policy and optimized
no-grid-charge policy are replayed as fallback candidates, so objective value
cannot be worse than these references. Runtime/memory O(intervals * grid states).

Default round-trip AC efficiency is .75 (the planner may pass measured values), split using the existing
HA RAW_PV conversion: discharge=1/1.192 and charge=.75/discharge. PV is already
DC, so incurs no AC charger loss. Terminal value is EUR/DC-kWh, conservative
zero by default; objective = grid cost - terminal value * final inventory.
Savings compare actual import costs (not terminal-adjusted objective).

Schedules are DATE-BOUND seven-weekday dictionaries, NOT recurring authorizations.
Consumers must enforce each window's data.plan_date and data.valid_until.
Windows include hold/off explicitly. No writes, clock reads, network or HA API.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
import math
from numbers import Real
from typing import Sequence

MODES = ('hold', 'serve', 'charge')
UTC = timezone.utc
_TOL = 1e-10


@dataclass(frozen=True)
class Params:
    capacity_kwh: float
    reserve_kwh: float
    initial_kwh: float
    pv_coupling: str  # Explicit confirmation required; only 'dc' supported.
    max_charge_kw: float = 1.0
    max_discharge_kw: float = 1.0
    discharge_efficiency: float = 1 / 1.192
    charge_efficiency: float = 0.75 / (1 / 1.192)
    energy_step_kwh: float = 0.05
    terminal_value_eur_kwh: float = 0.0
    grid_charge_limit_kwh: float | None = None
    decision_block_minutes: int = 0
    terminal_value_curve: tuple = ()  # (DC inventory, EUR credit), replaces linear credit
    switch_cost_eur: float = 0.0  # planning-only cost per mode change; never in reported cash


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    price_eur_kwh: float
    load_kwh: float
    pv_kwh: float


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone-aware datetime required')
    # Reject nonexistent local times as well as manually inconsistent fold values.
    back = value.astimezone(UTC).astimezone(value.tzinfo)
    if back.replace(tzinfo=None) != value.replace(tzinfo=None):
        raise ValueError('nonexistent local datetime')


def _intervals(intervals):
    rows = list(intervals)
    if not rows:
        raise ValueError('at least one interval required')
    previous = None
    for row in rows:
        if not isinstance(row, Interval):
            raise TypeError('intervals must contain Interval objects')
        _aware(row.start)
        _aware(row.end)
        start, end = row.start.astimezone(UTC), row.end.astimezone(UTC)
        if end <= start or (previous is not None and start != previous):
            raise ValueError('intervals must have positive duration and contiguous absolute times')
        previous = end
        for name in ('price_eur_kwh', 'load_kwh', 'pv_kwh'):
            _number(getattr(row, name), name)
        if row.load_kwh < 0 or row.pv_kwh < 0:
            raise ValueError('load and PV must be nonnegative')
    return rows


def _params(p):
    if not isinstance(p, Params):
        raise TypeError('params must be Params')
    if p.pv_coupling != 'dc':
        raise ValueError("explicit pv_coupling='dc' required")
    for name, value in asdict(p).items():
        if name not in ('pv_coupling', 'terminal_value_curve') and value is not None:
            _number(value, name)
    if (not 0 <= p.reserve_kwh <= p.capacity_kwh
            or not 0 <= p.initial_kwh <= p.capacity_kwh or p.capacity_kwh <= 0):
        raise ValueError('require reserve and initial independently within positive capacity')
    if p.max_charge_kw <= 0 or p.max_discharge_kw < 0 or p.energy_step_kwh <= 0:
        raise ValueError('power and energy step limits invalid')
    if not 0 < p.discharge_efficiency <= 1 or not 0 < p.charge_efficiency <= 1:
        raise ValueError('efficiencies must be in (0, 1]')
    # Round trip is configured or measured (battery_calibration); keep it physically plausible.
    if not 0.5 <= p.charge_efficiency * p.discharge_efficiency <= 0.95:
        raise ValueError('charge_efficiency * discharge_efficiency must be within 0.5..0.95')
    if p.terminal_value_eur_kwh < 0:
        raise ValueError('terminal inventory value must be nonnegative')
    if p.switch_cost_eur < 0:
        raise ValueError('switch cost must be nonnegative')
    if p.terminal_value_curve:
        if p.terminal_value_eur_kwh:
            raise ValueError('Curve replaces linear terminal credit; never add both')
        previous = None
        slope = math.inf
        for energy, value in p.terminal_value_curve:
            _number(energy, 'curve inventory'); _number(value, 'curve value')
            if value < 0 or energy < 0 or energy > p.capacity_kwh:
                raise ValueError('Invalid inventory curve')
            if previous:
                width = energy - previous[0]
                if width <= 0 or value < previous[1] - _TOL:
                    raise ValueError('Curve must be ordered and nondecreasing')
                marginal = (value - previous[1]) / width
                if previous[0] >= p.reserve_kwh:
                    if marginal > slope + _TOL:raise ValueError('Marginal value must decline above reserve')
                    slope = marginal
            previous = (energy, value)
        if p.terminal_value_curve[0][0] != 0 or p.terminal_value_curve[0][1] != 0 or p.terminal_value_curve[-1][0] != p.capacity_kwh:
            raise ValueError('Curve must cover zero through physical capacity')
    if p.grid_charge_limit_kwh is not None and not p.reserve_kwh <= p.grid_charge_limit_kwh <= p.capacity_kwh:
        raise ValueError('grid-charge ceiling must be between reserve and physical capacity')
    if isinstance(p.decision_block_minutes, bool) or not isinstance(p.decision_block_minutes, int) or p.decision_block_minutes < 0:
        raise ValueError('decision block must be a nonnegative integer number of minutes')


def _flow(row, energy, mode, p):
    hours = (row.end.astimezone(UTC) - row.start.astimezone(UTC)).total_seconds() / 3600
    charger = p.max_charge_kw * hours if mode == 'charge' else 0.0
    served = 0.0
    if mode == 'serve':
        served = min(row.load_kwh, p.max_discharge_kw * hours,
                     (row.pv_kwh + max(0.0, energy - p.reserve_kwh)) * p.discharge_efficiency)
    dc_needed = served / p.discharge_efficiency
    pv_direct = min(row.pv_kwh, dc_needed)
    battery_out = dc_needed - pv_direct
    remaining = energy - battery_out
    pv_stored = min(row.pv_kwh - pv_direct, max(0.0, p.capacity_kwh - remaining))
    remaining += pv_stored
    if p.grid_charge_limit_kwh is not None:
        # Charger runs at fixed power, but turns OFF on reaching its ceiling.
        # PV storage is allowed above that ceiling up to physical capacity.
        charger = min(charger, max(0.0, p.grid_charge_limit_kwh - remaining) / p.charge_efficiency)
    charger_stored = min(charger * p.charge_efficiency, max(0.0, p.capacity_kwh - remaining))
    remaining += charger_stored
    spill = row.pv_kwh - pv_direct - pv_stored + charger * p.charge_efficiency - charger_stored
    house_grid = row.load_kwh - served
    grid = house_grid + charger
    return dict(start=row.start.isoformat(), end=row.end.isoformat(), mode=mode,
                duration_hours=hours, price_eur_kwh=row.price_eur_kwh,
                load_kwh=row.load_kwh, pv_kwh=row.pv_kwh, initial_kwh=energy,
                terminal_kwh=remaining, charger_ac_kwh=charger,
                charger_stored_dc_kwh=charger_stored, pv_stored_dc_kwh=pv_stored,
                pv_direct_dc_kwh=pv_direct, battery_discharge_dc_kwh=battery_out,
                served_ac_kwh=served, house_grid_kwh=house_grid,
                grid_import_kwh=grid, spill_dc_kwh=max(0.0, spill),
                charge_loss_kwh=charger * (1 - p.charge_efficiency),
                discharge_loss_kwh=dc_needed - served,
                cost_eur=grid * row.price_eur_kwh)


def _better(a, b):
    """Lexicographic score: money, charger energy, transitions; stable mode order."""
    if b is None:
        return True
    for x, y in zip(a, b):
        if abs(x - y) > _TOL:
            return x < y
    return False


def _interpolate(grid, values, energy):
    if energy <= grid[0]:
        return values[0]
    if energy >= grid[-1]:
        return values[-1]
    lo = bisect_right(grid, energy) - 1
    fraction = (energy - grid[lo]) / (grid[lo + 1] - grid[lo])
    return tuple(a + fraction * (b - a) for a, b in zip(values[lo], values[lo + 1]))


def _decision_stages(rows, minutes):
    if not minutes:
        return [[row] for row in rows]
    span = minutes * 60
    stages = []
    previous_slot = None
    for row in rows:
        slot = math.floor(row.start.timestamp() / span)
        if row.end.timestamp() > (slot + 1) * span + _TOL:
            raise ValueError('interval crosses a decision-block boundary')
        if slot != previous_slot:
            stages.append([])
        stages[-1].append(row)
        previous_slot = slot
    return stages


def _stage_flow(stage, energy, mode, p):
    cost = charger = 0.0
    for row in stage:
        f = _flow(row, energy, mode, p)
        energy = f['terminal_kwh']
        cost += f['cost_eur']
        charger += f['charger_ac_kwh']
    return dict(cost_eur=cost, charger_ac_kwh=charger, terminal_kwh=energy)


def _choose(stage, energy, previous, p, allowed, grid, future):
    best, chosen = None, None
    for mode in allowed:
        f = _stage_flow(stage, energy, mode, p)
        rest = _interpolate(grid, future[mode], f['terminal_kwh'])
        switched = previous is not None and previous != mode
        # Relay/charger wear and fragmented windows: a small planning-only cost.
        score = (f['cost_eur'] + p.switch_cost_eur * switched + rest[0], f['charger_ac_kwh'] + rest[1],
                 switched + rest[2])
        if _better(score, best):
            best, chosen = score, mode
    return chosen, best


def inventory_value(p, energy):
    if not p.terminal_value_curve:return energy * p.terminal_value_eur_kwh
    grid = [point[0] for point in p.terminal_value_curve]
    values = [(point[1],) for point in p.terminal_value_curve]
    return _interpolate(grid, values, energy)[0]


def _dp_modes(rows, p, allow_charge):
    stages = _decision_stages(rows, p.decision_block_minutes)
    # Retain states below the reserve when starting depleted. Clamping them to
    # reserve would credit energy that has not actually been charged.
    lower = min(p.reserve_kwh, p.initial_kwh)
    span = p.capacity_kwh - lower
    count = math.floor(span / p.energy_step_kwh)
    grid = [lower + i * p.energy_step_kwh for i in range(count + 1)]
    if grid[-1] < p.capacity_kwh:
        grid.append(p.capacity_kwh)
    allowed = MODES if allow_charge else MODES[:2]
    locked = [any(_hold_only(row) for row in stage) for stage in stages]
    terminal = [(-inventory_value(p, energy), 0.0, 0) for energy in grid]
    future = {mode: terminal for mode in MODES}
    futures = [None] * len(stages)
    for index in range(len(stages) - 1, -1, -1):
        futures[index] = future
        options = ('hold',) if locked[index] else allowed
        future = {previous: [_choose(stages[index], energy, previous, p, options, grid, future)[1]
                             for energy in grid] for previous in MODES}
    energy, previous = p.initial_kwh, None
    modes = []
    for stage, future, hold_only in zip(stages, futures, locked):
        mode, _ = _choose(stage, energy, previous, p, ('hold',) if hold_only else allowed, grid, future)
        modes.extend([mode] * len(stage))
        energy = _stage_flow(stage, energy, mode, p)['terminal_kwh']
        previous = mode
    return modes


def _replay(rows, modes, p):
    energy, flows = p.initial_kwh, []
    for row, mode in zip(rows, modes):
        flow = _flow(row, energy, mode, p)
        flows.append(flow)
        energy = flow['terminal_kwh']
    cost = math.fsum(f['cost_eur'] for f in flows)
    return dict(modes=list(modes), intervals=flows, cost_eur=cost,
                initial_kwh=p.initial_kwh, terminal_kwh=energy,
                carryover_value_eur=inventory_value(p, energy),
                objective_eur=cost - inventory_value(p, energy))


def _select(plans, switch_cost=0.0):
    selected, best = None, None
    for plan in plans:
        modes = plan['modes']
        switches = sum(a != b for a, b in zip(modes, modes[1:]))
        score = (plan['objective_eur'] + switch_cost * switches,
                 math.fsum(f['charger_ac_kwh'] for f in plan['intervals']), switches)
        if _better(score, best):
            selected, best = plan, score
    return selected


def optimize(intervals: Sequence[Interval], params: Params) -> dict:
    """Return replayed plan, parameters and separate baseline/no-charge savings.

    No input is mutated. Reference plans include their full physical flows.
    Mode ties prefer less charger energy then fewer transitions; interpolated
    transition counts are only a heuristic, not an exact continuous optimum.
    """
    _params(params)
    rows = _intervals(intervals)
    baseline = _replay(rows, ['hold' if _hold_only(row) else 'serve' for row in rows], params)
    no_charge = _select([_replay(rows, _dp_modes(rows, params, False), params), baseline], params.switch_cost_eur)
    plan = _select([_replay(rows, _dp_modes(rows, params, True), params), no_charge], params.switch_cost_eur)
    return dict(plan, params=asdict(params), comparison=dict(
        serve_baseline=baseline, optimized_no_charge=no_charge,
        hold_benefit_eur=baseline['cost_eur'] - no_charge['cost_eur'],
        incremental_grid_charge_benefit_eur=no_charge['cost_eur'] - plan['cost_eur'],
        total_savings_eur=baseline['cost_eur'] - plan['cost_eur']),
        approximation='Interpolated value-grid DP; continuous feasible replay; no global optimality guarantee.')


def _ambiguous(value):
    a, b = value.replace(fold=0), value.replace(fold=1)
    return a.utcoffset() != b.utcoffset()


def _hold_only(row):
    """Repeated DST wall-clock minutes cannot be expressed in HA schedules.
    Plan them as hold (both off) instead of failing the whole run later."""
    zone = row.start.tzinfo
    probe, end = row.start.astimezone(UTC), row.end.astimezone(UTC)
    while probe < end:
        if _ambiguous(probe.astimezone(zone)):
            return True
        probe += timedelta(minutes=1)
    return False


def schedules(intervals: Sequence[Interval], modes: Sequence[str], valid_until: datetime) -> dict:
    """Create mon..sun lists of {start,end,mode,data:{plan_date,valid_until}}.

    Split local midnight, merge adjacent same-mode windows on the same date,
    emit 24:00 for midnight endings. Require minute-aligned boundaries, a
    single timezone and at most seven local calendar dates. Reject ANY active
    window touching a repeated DST wall-clock minute (either fold). Hold
    windows may span repeated hours because their only action is both off.
    valid_until must cover the horizon and must be enforced by the consumer.
    """
    rows = _intervals(intervals)
    modes = list(modes)
    _aware(valid_until)
    if len(modes) != len(rows) or any(mode not in MODES for mode in modes):
        raise ValueError('one valid mode per interval required')
    if valid_until.astimezone(UTC) < rows[-1].end.astimezone(UTC):
        raise ValueError('valid_until must cover the horizon')
    zone = rows[0].start.tzinfo
    for row in rows:
        for point in (row.start, row.end):
            if point.tzinfo != zone:
                raise ValueError('schedules require a single timezone')
            if point.second or point.microsecond:
                raise ValueError('schedule boundaries must be minute aligned')
    last_date = (rows[-1].end.astimezone(UTC) - timedelta(microseconds=1)).astimezone(zone).date()
    if (last_date - rows[0].start.date()).days >= 7:
        raise ValueError('schedule horizon must span at most seven calendar dates')
    result = {name: [] for name in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')}
    for row, mode in zip(rows, modes):
        cursor, end = row.start.astimezone(UTC), row.end.astimezone(UTC)
        if mode != 'hold':
            probe = cursor
            while probe < end:
                if _ambiguous(probe.astimezone(zone)):
                    raise ValueError('ambiguous DST wall clock hour in active window')
                probe += timedelta(minutes=1)
        while cursor < end:
            local = cursor.astimezone(zone)
            midnight = datetime.combine(local.date() + timedelta(days=1), time(), zone).astimezone(UTC)
            stop = min(end, midnight)
            if stop <= cursor:
                raise ValueError('unsupported local midnight transition')
            stop_local = stop.astimezone(zone)
            start_text = local.strftime('%H:%M')
            end_text = '24:00' if stop == midnight else stop_local.strftime('%H:%M')
            windows = result[('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[local.weekday()]]
            data = dict(plan_date=local.date().isoformat(), valid_until=valid_until.isoformat())
            if windows and windows[-1]['end'] == start_text and windows[-1]['mode'] == mode and windows[-1]['data'] == data:
                windows[-1]['end'] = end_text
            else:
                windows.append(dict(start=start_text, end=end_text, mode=mode, data=data))
            cursor = stop
    return result
