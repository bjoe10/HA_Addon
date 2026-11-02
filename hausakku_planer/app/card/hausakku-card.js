// Hausakku-Planer dashboard card: the Tibber Prices chart with the battery, the published plan and a clock.
// Shipped with the add-on, which fills in ADDON (its helpers, the battery entities and capacity) when it installs it.
const ADDON = {}; // hausakku-addon-defaults
const DEFAULTS = {
  reserve_percent: 10,
  charge_schedule: 'schedule.hap_netzladen',
  serve_schedule: 'schedule.hap_entladen',
  expiry_entity: 'input_datetime.hap_plan_gueltig_bis',
  permission_entity: 'input_boolean.hap_planer_freigabe',
  owner_entity: 'input_boolean.hap_regler_uebernommen',
  target_soc_entity: 'input_number.hap_ziel_soc',
  plan_report_entity: 'sensor.hap_bericht',
};
// The card's own options; everything else goes to the Tibber chart
const OWN_KEYS = [
  'battery_entity', 'battery_kwh_entity', 'capacity_kwh', 'target_soc_entity', 'reserve_percent',
  'battery_power_entity', 'pv_power_entity', 'inverter_power_entity', 'charger_power_entity',
  'grid_import_entity', 'grid_export_entity', 'grid_today_entity', 'grid_cost_entity', 'meter_entity',
  'plan_report_entity', 'charge_schedule', 'serve_schedule', 'expiry_entity', 'permission_entity', 'owner_entity',
  'strategy_entity', 'mode_entity', 'best_price_entity', 'peak_price_entity', 'clock', 'kiosk', 'night_mode', 'soc_line',
];
const option = (config, key) => config[key] ?? ADDON[key] ?? DEFAULTS[key];
const ACTIVE_WATTS = 10;
const CHART_ELEMENT = 'tibber-prices-chart-card';
const CHART_SCRIPT_PATH = '/tibber_prices_frontend/tibber-prices-cards.js';
const WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

export function batteryFillPresentation(state) {
  if (state === undefined || state === null || String(state).trim() === '' || ['unknown', 'unavailable'].includes(String(state).toLowerCase())) {
    return { available: false, percent: 0, label: '—', tone: 'unavailable' };
  }
  const numeric = Number(state);
  if (!Number.isFinite(numeric)) return { available: false, percent: 0, label: '—', tone: 'unavailable' };
  const percent = Math.round(Math.max(0, Math.min(100, numeric)));
  const tone = percent <= 10 ? 'low' : percent <= 25 ? 'warning' : 'normal';
  return { available: true, percent, label: `${percent}%`, tone };
}

function numericState(state) {
  if (state === undefined || state === null || String(state).trim() === '') return NaN;
  return Number(state);
}

const kwhFormat = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

// Battery energy: the kWh sensor where there is one (its capacity follows from the SoC), else SoC × capacity
export function batteryEnergyPresentation(socState, kwhState, reservePercent = DEFAULTS.reserve_percent, capacityKwh = NaN) {
  const soc = numericState(socState);
  let kwh = numericState(kwhState);
  const measured = Number.isFinite(soc) && Number.isFinite(kwh) && soc > 0 && kwh > 0;
  const capacity = measured ? (kwh / soc) * 100 : Number(capacityKwh);
  if (!measured && Number.isFinite(soc) && capacity > 0) kwh = (Math.max(0, soc) * capacity) / 100;
  if (!Number.isFinite(soc) || !Number.isFinite(kwh) || !(capacity > 0)) return { available: false, label: '' };
  return {
    available: true,
    kwh,
    capacity,
    reserveKwh: (capacity * reservePercent) / 100,
    label: `${kwhFormat.format(kwh)} kWh`,
  };
}

export function chargeTargetPresentation(socState, targetState, kwhState, capacityKwh = NaN) {
  const soc = numericState(socState);
  const target = numericState(targetState);
  const energy = batteryEnergyPresentation(socState, kwhState, DEFAULTS.reserve_percent, capacityKwh);
  if (!energy.available || !Number.isFinite(target) || target <= soc) return null;
  const goal = Math.min(target, 100);
  const kwh = (energy.capacity * (goal - soc)) / 100;
  return { targetKwh: (energy.capacity * goal) / 100, kwh, label: `+${kwhFormat.format(kwh)} kWh bis Ziel` };
}

const powerFormat = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function formatPower(state) {
  const watts = numericState(state);
  if (!Number.isFinite(watts)) return { label: '—', active: false };
  const abs = Math.abs(watts);
  return {
    label: abs >= 1000 ? `${powerFormat.format(abs / 1000)} kW` : `${Math.round(abs)} W`,
    active: abs >= ACTIVE_WATTS,
  };
}

// The BMS power sensor carries no sign, so direction comes from the charger and inverter draw.
export function batteryPowerDirection({ batteryState, chargerState, inverterState, pvState }) {
  const battery = numericState(batteryState);
  if (!Number.isFinite(battery) || Math.abs(battery) < ACTIVE_WATTS) return null;
  const charger = numericState(chargerState);
  const inverter = numericState(inverterState);
  const pv = numericState(pvState);
  const chargerOn = Number.isFinite(charger) && charger >= ACTIVE_WATTS;
  const inverterOn = Number.isFinite(inverter) && inverter >= ACTIVE_WATTS;
  if (chargerOn && !inverterOn) return 'charge';
  if (inverterOn && !chargerOn) return 'discharge';
  if (!chargerOn && !inverterOn && Number.isFinite(pv) && pv >= ACTIVE_WATTS) return 'charge';
  return null;
}

// The meter's two directions: what comes from the grid, else what goes into it (shown negative)
export function gridPresentation(importState, exportState) {
  const imported = numericState(importState);
  const exported = numericState(exportState);
  if (!Number.isFinite(imported) && !Number.isFinite(exported)) return { label: '—', active: false, title: '' };
  if (Number.isFinite(exported) && exported >= ACTIVE_WATTS && !(imported >= ACTIVE_WATTS)) {
    return { label: `−${formatPower(exported).label}`, active: true, title: 'Einspeisung ins Netz' };
  }
  return { ...formatPower(imported), title: 'Bezug aus dem Netz' };
}

function moneyFormat(value, unit) {
  try {
    return new Intl.NumberFormat('de-DE', { style: 'currency', currency: unit || 'EUR' }).format(value);
  } catch (error) {
    return `${value.toFixed(2)} ${unit}`;
  }
}

export function gridTodayPresentation(kwhState, costState, costUnit = 'EUR') {
  const kwh = numericState(kwhState);
  if (!Number.isFinite(kwh)) return null;
  const cost = numericState(costState);
  return { label: `${kwhFormat.format(kwh)} kWh`, cost: Number.isFinite(cost) ? moneyFormat(cost, costUnit) : '' };
}

// A best or peak price period for the clock: running ("bis 05:45") or next ("22:45–05:45", "Di 06:45–08:15")
export function periodPresentation(startState, endState, now, timeZone = 'UTC') {
  const start = typeof startState === 'number' ? startState : Date.parse(startState);
  const end = typeof endState === 'number' ? endState : Date.parse(endState);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= now || end <= start) return null;
  const clock = new Intl.DateTimeFormat('de-DE', { timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const day = new Intl.DateTimeFormat('de-DE', { timeZone, weekday: 'short' });
  const date = new Intl.DateTimeFormat('en-CA', { timeZone });
  if (start <= now) return { active: true, text: `bis ${clock.format(end)}` };
  const startDay = date.format(start) === date.format(now) ? '' : `${day.format(start).replace('.', '')} `;
  return { active: false, text: `${startDay}${clock.format(start)}–${clock.format(end)}` };
}

export function nextPeriod(periods, now) {
  if (!Array.isArray(periods)) return null;
  return periods
    .map((period) => ({ start: Date.parse(period?.start), end: Date.parse(period?.end) }))
    .filter((period) => Number.isFinite(period.start) && Number.isFinite(period.end) && period.end > now)
    .sort((a, b) => a.start - b.start)[0] || null;
}

export function clockPresentation(now, timeZone = 'UTC') {
  return {
    time: new Intl.DateTimeFormat('de-DE', { timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(now),
    date: new Intl.DateTimeFormat('de-DE', { timeZone, weekday: 'long', day: 'numeric', month: 'long' }).format(now),
  };
}

// The planner's published battery energy (report sensor attribute soc_plan) as [time, kWh] points
export function socPlanPoints(socPlan) {
  if (!socPlan || !Array.isArray(socPlan.minutes) || !Array.isArray(socPlan.kwh)) return [];
  const start = Date.parse(socPlan.start);
  if (!Number.isFinite(start)) return [];
  const points = Number.isFinite(socPlan.initial_kwh) ? [[start, socPlan.initial_kwh]] : [];
  socPlan.minutes.forEach((minutes, index) => {
    const kwh = socPlan.kwh[index];
    if (Number.isFinite(minutes) && Number.isFinite(kwh)) points.push([start + minutes * 60000, kwh]);
  });
  return points;
}

// A history/history_during_period answer (minimal, without attributes) as [time, value] points
export function historyPoints(response, entityId) {
  const rows = response?.[entityId];
  if (!Array.isArray(rows)) return [];
  const points = [];
  for (const row of rows) {
    const value = numericState(row.s ?? row.state);
    const at = row.lu !== undefined ? row.lu * 1000 : Date.parse(row.last_updated || row.last_changed);
    if (Number.isFinite(value) && Number.isFinite(at)) points.push([at, value]);
  }
  return points;
}

// The points within [from, to], the edges interpolated so a line ends exactly where the range does
export function clipSeries(points, from, to) {
  const out = [];
  if (!(to > from)) return out;
  const between = (a, b, at) => a[1] + ((b[1] - a[1]) * (at - a[0])) / (b[0] - a[0]);
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index];
    const previous = points[index - 1];
    if (previous && previous[0] < from && point[0] > from) out.push([from, between(previous, point, from)]);
    if (point[0] >= from && point[0] <= to) out.push(point);
    if (previous && previous[0] < to && point[0] > to) {
      out.push([to, between(previous, point, to)]);
      break;
    }
  }
  return out;
}

const MODE_LABELS = { hold: 'Halten', charge: 'Netzladen', serve: 'WR-Freigabe', conflict: 'Konflikt' };
const REGEL_LABELS = {
  versorgen: 'Versorgen', aufheben: 'Halten', netzladen: 'Netzladen', plan_fallback: 'Ersatzbetrieb',
  sicher_aus: 'Schutzstopp', reserve: 'Reserve', ladepause: 'Ladepause', manuell: 'Manuell',
};
const PLAN_TO_REGEL = { hold: 'aufheben', charge: 'netzladen', serve: 'versorgen' };
const PROTECTION_MODES = ['sicher_aus', 'reserve', 'ladepause'];
const INVALID_STRATEGIES = ['abgelaufen', 'fehler', 'unknown', 'unavailable'];

export function formatDuration(ms) {
  const minutes = Math.max(0, Math.round(ms / 60000));
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} min`;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

function describeStamp(ms, now, timeZone) {
  const clock = new Intl.DateTimeFormat('de-DE', { timeZone, hour: '2-digit', minute: '2-digit' });
  const day = new Intl.DateTimeFormat('de-DE', { timeZone, weekday: 'short', day: '2-digit', month: '2-digit' });
  return day.format(ms) === day.format(now) ? clock.format(ms) : `${day.format(ms)} ${clock.format(ms)}`;
}

export function segmentTooltip(segment, now, timeZone = 'UTC') {
  const label = MODE_LABELS[segment.mode] || segment.mode;
  return `${label}: ${describeStamp(segment.start, now, timeZone)} – ${describeStamp(segment.end, now, timeZone)} (${formatDuration(segment.end - segment.start)})`;
}

export function phaseInvalidReason({ plannerEnabled, expiry, now, strategy, timeZone = 'UTC' }) {
  if (!plannerEnabled) return 'Planer-Freigabe ist aus – Phasenplan wird nicht angezeigt';
  if (!Number.isFinite(expiry)) return 'Kein Ablaufzeitpunkt des Plans vorhanden';
  if (expiry <= now) return `Plan abgelaufen (${describeStamp(expiry, now, timeZone)}) – wartet auf Neuplanung`;
  if (INVALID_STRATEGIES.includes(strategy)) return `Planstatus: ${strategy}`;
  return 'Kein gültiger Phasenplan';
}

export function currentModePresentation(regelmodus, windows, now, valid) {
  if (!regelmodus || ['unknown', 'unavailable'].includes(regelmodus)) return null;
  const label = REGEL_LABELS[regelmodus] || regelmodus;
  if (!valid) return { label, differs: false, title: '' };
  const active = new Set((windows || []).filter((w) => w.start <= now && now < w.end).map((w) => w.mode));
  if (active.size > 1) return { label, differs: false, title: '' };
  const plannedMode = active.size === 0 ? 'hold' : [...active][0];
  if (PLAN_TO_REGEL[plannedMode] === regelmodus) return { label, differs: false, title: 'Entspricht dem Plan' };
  const protection = PROTECTION_MODES.includes(regelmodus) ? ' – Schutz hat Vorrang' : '';
  return { label, differs: true, title: `Plan sieht ${MODE_LABELS[plannedMode]} vor${protection}` };
}

function parseClock(value) {
  const match = /^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?$/.exec(String(value || ''));
  if (!match) return null;
  return {
    hour: Number(match[1]),
    minute: Number(match[2]),
    second: Number(match[3] || 0),
    millisecond: Math.floor(Number(`0.${match[4] || 0}`) * 1000),
  };
}

export function zonedWallTimeMs(date, time, timeZone = 'UTC') {
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(date || ''));
  const clock = parseClock(time);
  if (!dateMatch || !clock) return NaN;
  const [year, month, day] = dateMatch.slice(1).map(Number);
  const target = Date.UTC(year, month - 1, day, clock.hour, clock.minute, clock.second);
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  let guess = target;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const parts = Object.fromEntries(formatter.formatToParts(new Date(guess)).map((part) => [part.type, part.value]));
    const observed = Date.UTC(
      Number(parts.year), Number(parts.month) - 1, Number(parts.day),
      Number(parts.hour), Number(parts.minute), Number(parts.second),
    );
    const delta = target - observed;
    guess += delta;
    if (delta === 0) break;
  }
  return guess + clock.millisecond;
}

function nextLocalDate(date) {
  const [year, month, day] = date.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day + 1)).toISOString().slice(0, 10);
}

export function scheduleWindows(schedules, timeZone = 'UTC', ids = { charge: 'hap_netzladen', serve: 'hap_entladen' }) {
  if (!Array.isArray(schedules)) return [];
  const windows = [];
  for (const [scheduleId, mode] of [[ids.charge, 'charge'], [ids.serve, 'serve']]) {
    const schedule = schedules.find((item) => item.id === scheduleId || item.entity_id === `schedule.${scheduleId}`);
    if (!schedule) continue;
    for (const weekday of WEEKDAYS) {
      for (const block of schedule[weekday] || []) {
        const planDate = block.data?.plan_date;
        if (!/^\d{4}-\d{2}-\d{2}$/.test(planDate || '')) continue;
        const start = zonedWallTimeMs(planDate, block.from, timeZone);
        let end = zonedWallTimeMs(planDate, block.to, timeZone);
        if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
        if (end <= start) end = zonedWallTimeMs(nextLocalDate(planDate), block.to, timeZone);
        if (end > start) windows.push({ start, end, mode });
      }
    }
  }
  return windows.sort((a, b) => a.start - b.start || a.end - b.end);
}

export function buildPhaseSegments(windows, planStart, planEnd, viewStart, viewEnd, now) {
  const start = Math.max(planStart, viewStart, now);
  const end = Math.min(planEnd, viewEnd);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return [];
  const clipped = (windows || []).filter((window) =>
    ['charge', 'serve'].includes(window.mode) && Number.isFinite(window.start) && Number.isFinite(window.end) && window.end > start && window.start < end,
  ).map((window) => ({
    start: Math.max(start, window.start),
    end: Math.min(end, window.end),
    mode: window.mode,
  }));
  const points = [...new Set([start, end, ...clipped.flatMap((window) => [window.start, window.end])])].sort((a, b) => a - b);
  const segments = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const a = points[index];
    const b = points[index + 1];
    if (b <= a) continue;
    const active = new Set(clipped.filter((window) => window.start < b && window.end > a).map((window) => window.mode));
    const mode = active.size === 0 ? 'hold' : active.size > 1 ? 'conflict' : [...active][0];
    const previous = segments[segments.length - 1];
    if (previous?.mode === mode && previous.end === a) previous.end = b;
    else segments.push({ start: a, end: b, mode });
  }
  return segments;
}

export function phaseControlCaption(hass, validPlan, ownerEntity) {
  const active = validPlan === true && hass?.states?.[ownerEntity]?.state === 'on';
  return { title: active ? 'Phasenplan · Regelung aktiv' : 'Phasenplan' };
}

const HTMLElementBase = globalThis.HTMLElement || class {};

class TibberPricesBatteryChartCard extends HTMLElementBase {
  setConfig(config) {
    if (!config || !config.device_id) throw new Error('Bitte device_id für die Tibber-Preiskarte angeben.');
    const get = (key) => option(config, key);
    this._batteryEntity = get('battery_entity');
    if (!this._batteryEntity) throw new Error('Bitte battery_entity (Akku-Ladestand in %) angeben oder die Karte über das Add-on einrichten.');
    this._kwhEntity = get('battery_kwh_entity');
    this._capacityKwh = Number(get('capacity_kwh'));
    this._targetEntity = get('target_soc_entity');
    this._powerEntities = {
      battery: get('battery_power_entity'),
      pv: get('pv_power_entity'),
      inverter: get('inverter_power_entity'),
      charger: get('charger_power_entity'),
      gridImport: get('grid_import_entity'),
      gridExport: get('grid_export_entity'),
      gridToday: get('grid_today_entity'),
      gridCost: get('grid_cost_entity'),
      meter: get('meter_entity'),
    };
    this._planEntities = {
      charge: String(get('charge_schedule')).replace(/^schedule\./, ''),
      serve: String(get('serve_schedule')).replace(/^schedule\./, ''),
      expiry: get('expiry_entity'),
      permission: get('permission_entity'),
      owner: get('owner_entity'),
      strategy: get('strategy_entity'),
      mode: get('mode_entity'),
    };
    this._periodEntities = { best: config.best_price_entity, peak: config.peak_price_entity };
    this._deviceId = config.device_id;
    this._showClock = config.clock === true;
    this._socLine = config.soc_line !== false;
    this._planReportEntity = get('plan_report_entity');
    this._kiosk = config.kiosk === true;
    this.toggleAttribute('data-kiosk', this._kiosk);
    this._nightMode = config.night_mode === true;
    this._appliedAppearance = undefined;
    const reserve = Number(get('reserve_percent'));
    this._reservePercent = Number.isFinite(reserve) && reserve >= 0 && reserve < 100 ? reserve : DEFAULTS.reserve_percent;
    const chartConfig = { ...config };
    for (const key of OWN_KEYS) delete chartConfig[key];
    chartConfig.type = 'custom:tibber-prices-chart-card';
    this._chartConfig = chartConfig;
    this._build();
    this._ensureChart();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._chart && !customElements.get(CHART_ELEMENT)) {
      this._loadChartScript();
    } else if (this._chart) {
      this._applyAppearance(this._chart);
      this._chart.hass = hass;
      this._mountChartExtras(this._chart);
    }
    this._renderBatteryFill();
    this._renderPower();
    this._renderClock();
    this._loadPlan();
    this._renderPhaseLane();
  }

  connectedCallback() {
    clearInterval(this._refreshTimer);
    this._refreshTimer = setInterval(() => this._loadPlan(true), 60000);
    this._scheduleClock();
    if (this._hass) {
      this._loadPlan(true);
      if (this._chart && customElements.get(CHART_ELEMENT)) this._mountChartExtras(this._chart);
    }
  }

  disconnectedCallback() {
    clearInterval(this._refreshTimer);
    clearTimeout(this._remountTimer);
    clearTimeout(this._clockTimer);
    this._plotObserver?.disconnect();
  }

  getCardSize() { return 7; }
  getGridOptions() { return { columns: 'full', rows: 7, min_columns: 6, min_rows: 5 }; }

  _build() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>:host{display:flex;flex-direction:column;height:100%}:host([data-kiosk]){height:100vh}.chart-slot{display:flex;flex:1;flex-direction:column;min-height:0}.chart-slot>*{flex:1;min-height:0}.error{color:var(--error-color);padding:8px 16px}.status{color:var(--secondary-text-color);font-size:13px;padding:8px 16px}.status[data-error='true']{color:var(--error-color)}</style><div class="error" hidden></div><div class="status" hidden></div><div class="chart-slot"></div>`;
    this._chartSlot = root.querySelector('.chart-slot');
    this._error = root.querySelector('.error');
    this._status = root.querySelector('.status');
  }

  _showStatus(text, isError = false) {
    if (!this._status) return;
    this._status.textContent = text;
    this._status.hidden = !text;
    this._status.dataset.error = String(isError);
  }

  // The chart script is a dashboard resource; on slow or casting browsers it can arrive late or
  // not at all, so wait for it, then load it ourselves and say why if that fails too
  _loadChartScript() {
    if (this._scriptLoad || customElements.get(CHART_ELEMENT) || !this._hass) return;
    this._showStatus('Tibber-Diagramm wird geladen …');
    const defined = () => Promise.race([
      customElements.whenDefined(CHART_ELEMENT),
      new Promise((resolve) => setTimeout(resolve, 5000)),
    ]);
    this._scriptLoad = (async () => {
      try {
        await defined();
        if (customElements.get(CHART_ELEMENT)) return;
        const url = typeof this._hass.hassUrl === 'function' ? this._hass.hassUrl(CHART_SCRIPT_PATH) : CHART_SCRIPT_PATH;
        await new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.type = 'module';
          script.src = url;
          script.onload = resolve;
          script.onerror = () => reject(new Error(`${url} nicht ladbar`));
          document.head.append(script);
        });
        await defined();
        if (!customElements.get(CHART_ELEMENT)) throw new Error('Skript geladen, Karte aber nicht registriert');
      } catch (error) {
        this._showStatus(`Tibber-Diagramm nicht verfügbar: ${error?.message || error}`, true);
        setTimeout(() => { this._scriptLoad = null; }, 30000);
      }
    })();
  }

  _renderBatteryFill() {
    if (!this._batteryLevel || !this._hass || !this._batteryEntity) return;
    const state = this._hass.states[this._batteryEntity]?.state;
    const fill = batteryFillPresentation(state);
    this._batteryLevel.dataset.tone = fill.tone;
    this._batteryLevelFill.style.width = `${fill.percent}%`;
    const energy = batteryEnergyPresentation(state, this._hass.states[this._kwhEntity]?.state, this._reservePercent, this._capacityKwh);
    this._batteryLevelValue.textContent = energy.available ? energy.label : '—';
    this._batteryLevel.setAttribute('aria-label', energy.available ? `Batterie-Füllstand ${energy.label}` : 'Batterie-Füllstand nicht verfügbar');
    if (fill.available) this._batteryLevelTrack.setAttribute('aria-valuenow', String(fill.percent));
    else this._batteryLevelTrack.removeAttribute('aria-valuenow');
    if (this._markReserve) {
      this._markReserve.style.left = `${this._reservePercent}%`;
      const soc = numericState(state);
      const target = numericState(this._hass.states[this._targetEntity]?.state);
      const showTarget = fill.available && Number.isFinite(target) && target > soc;
      this._markTarget.hidden = !showTarget;
      if (showTarget) this._markTarget.style.left = `${Math.min(target, 100)}%`;
      const goal = chargeTargetPresentation(state, this._hass.states[this._targetEntity]?.state, this._hass.states[this._kwhEntity]?.state, this._capacityKwh);
      this._batteryLevelTrack.title = energy.available
        ? `Kapazität ca. ${kwhFormat.format(energy.capacity)} kWh · Reserve ${kwhFormat.format(energy.reserveKwh)} kWh${goal ? ` · Ladeziel ${kwhFormat.format(goal.targetKwh)} kWh` : ''}`
        : '';
    }
  }

  _renderPower() {
    if (!this._powerValues || !this._hass) return;
    const stateOf = (id) => this._hass.states[id]?.state;
    const entities = this._powerEntities;
    const direction = batteryPowerDirection({
      batteryState: stateOf(entities.battery),
      chargerState: stateOf(entities.charger),
      inverterState: stateOf(entities.inverter),
      pvState: stateOf(entities.pv),
    });
    const tiles = this._powerTiles;
    this._batteryLevel.dataset.flow = direction || 'idle';
    for (const key of ['battery', 'pv', 'inverter']) {
      const exists = Boolean(entities[key] && this._hass.states[entities[key]]);
      const element = this._powerValues[key];
      // The battery tile stays for its energy; without a power sensor only its power goes
      if (key === 'battery') element.hidden = !exists;
      else tiles[key].hidden = !exists;
      const power = formatPower(stateOf(entities[key]));
      const arrow = key === 'battery' && direction ? (direction === 'charge' ? ' ↑' : ' ↓') : '';
      element.textContent = `${power.label}${arrow}`;
      element.dataset.active = String(power.active);
      element.title = key === 'battery' && direction ? (direction === 'charge' ? 'Akku lädt' : 'Akku entlädt') : '';
      tiles[key].dataset.state = key === 'battery' ? direction || 'idle' : power.active ? 'active' : 'idle';
    }
    const hasGrid = Boolean((entities.gridImport && this._hass.states[entities.gridImport]) || (entities.gridExport && this._hass.states[entities.gridExport]));
    tiles.grid.hidden = !hasGrid;
    if (hasGrid) {
      const grid = gridPresentation(stateOf(entities.gridImport), stateOf(entities.gridExport));
      this._powerValues.grid.textContent = grid.label;
      this._powerValues.grid.dataset.active = String(grid.active);
      tiles.grid.title = grid.title;
      tiles.grid.dataset.state = !grid.active ? 'idle' : grid.label.startsWith('−') ? 'export' : 'import';
    }
    const costUnit = this._hass.states[entities.gridCost]?.attributes?.unit_of_measurement;
    const today = gridTodayPresentation(stateOf(entities.gridToday), stateOf(entities.gridCost), costUnit);
    tiles.today.hidden = !today;
    if (today) {
      const meter = numericState(stateOf(entities.meter));
      this._powerValues.today.textContent = today.label;
      this._powerValues.today.dataset.active = 'true';
      this._todayCost.textContent = today.cost;
      tiles.today.title = Number.isFinite(meter) ? `Bezug heute · Zählerstand ${kwhFormat.format(meter)} kWh` : 'Bezug heute';
    }
  }

  _renderClock() {
    if (!this._clockTime) return;
    const now = Date.now();
    const timeZone = this._hass?.config?.time_zone || 'UTC';
    const clock = clockPresentation(now, timeZone);
    if (this._clockShown !== clock.time) {
      this._clockShown = clock.time;
      const [hours, minutes] = clock.time.split(':');
      this._clockTime.innerHTML = `${hours}<span class="battery-clock__colon">:</span>${minutes}`;
    }
    if (this._clockDate.textContent !== clock.date) this._clockDate.textContent = clock.date;
    const states = this._hass?.states || {};
    const period = (entity) => {
      const next = nextPeriod(states[entity]?.attributes?.periods, now);
      return next ? periodPresentation(next.start, next.end, now, timeZone) : null;
    };
    const lines = [
      ['good', 'günstig', period(this._periodEntities.best || this._tibberEntity('best_price_period'))],
      ['bad', 'teuer', period(this._periodEntities.peak || this._tibberEntity('peak_price_period'))],
    ].filter(([, , shown]) => shown)
      .map(([tone, word, shown]) => `<div class="battery-clock__period" data-tone="${tone}"><i></i>${shown.active ? `jetzt ${word} ` : `${word} `}${shown.text}</div>`)
      .join('');
    if (this._clockPeriods.innerHTML !== lines) this._clockPeriods.innerHTML = lines;
  }

  // An entity of the Tibber Prices home (its device) by translation key, found in the entity registry
  _tibberEntity(translationKey) {
    const registry = this._hass?.entities;
    if (!registry || !this._deviceId) return undefined;
    if (this._tibberRegistry !== registry) {
      this._tibberRegistry = registry;
      this._tibberEntities = {};
      for (const entry of Object.values(registry)) {
        if (entry.platform === 'tibber_prices' && entry.device_id === this._deviceId && entry.translation_key) {
          this._tibberEntities[entry.translation_key] = entry.entity_id;
        }
      }
    }
    return this._tibberEntities[translationKey];
  }

  // One update a minute, just after it turns
  _scheduleClock() {
    clearTimeout(this._clockTimer);
    if (!this._showClock) return;
    this._clockTimer = setTimeout(() => {
      this._renderClock();
      this._scheduleClock();
    }, 60000 - (Date.now() % 60000) + 50);
  }

  // The measured battery energy of the span shown, refreshed every two minutes
  _loadSocHistory(from) {
    if (!this._hass?.callWS || this._socHistoryLoad) return;
    if (this._socHistoryFrom === from && Date.now() - (this._socHistoryAt || 0) < 120000) return;
    const hass = this._hass;
    this._socHistoryLoad = (async () => {
      try {
        const response = await hass.callWS({
          type: 'history/history_during_period',
          start_time: new Date(from).toISOString(),
          end_time: new Date().toISOString(),
          entity_ids: [this._kwhEntity || this._batteryEntity],
          minimal_response: true,
          no_attributes: true,
          significant_changes_only: false,
        });
        this._socHistory = historyPoints(response, this._kwhEntity || this._batteryEntity);
        this._socHistoryIsSoc = !this._kwhEntity;
      } catch (error) {
        this._socHistory = [];
      } finally {
        this._socHistoryFrom = from;
        this._socHistoryAt = Date.now();
        this._socHistoryLoad = null;
        this._renderPhaseLane();
      }
    })();
  }

  // The battery's energy over the chart: measured up to now (solid), the published plan after (dashed)
  _renderSoc(geo, plot, now) {
    const layer = this._socLayer;
    if (!layer) return;
    const width = plot?.clientWidth;
    const height = plot?.clientHeight;
    if (!this._socLine || !geo || !width || !height || !(geo.to > geo.from)) {
      layer.replaceChildren();
      this._socMarkup = '';
      if (this._socKey) this._socKey.hidden = true;
      return;
    }
    const states = this._hass.states;
    const report = states[this._planReportEntity];
    if (report !== this._socPlanState) {
      this._socPlanState = report;
      this._socPlan = report?.attributes?.soc_plan;
      this._socPlanPoints = socPlanPoints(this._socPlan);
    }
    const planEnd = Date.parse(this._socPlan?.valid_until);
    const energy = batteryEnergyPresentation(states[this._batteryEntity]?.state, states[this._kwhEntity]?.state, this._reservePercent, this._capacityKwh);
    const current = energy.available ? energy.kwh : NaN;
    const history = this._socHistoryIsSoc
      ? (energy.available ? (this._socHistory || []).map(([at, soc]) => [at, (soc * energy.capacity) / 100]) : [])
      : this._socHistory || [];
    const past = clipSeries(
      [...history, ...(Number.isFinite(current) ? [[now, current]] : [])],
      geo.from,
      Math.min(now, geo.to),
    );
    const planned = Number.isFinite(planEnd) && planEnd > now
      ? clipSeries(this._socPlanPoints || [], Math.max(now, geo.from), Math.min(planEnd, geo.to))
      : [];
    this._loadSocHistory(geo.from);
    const capacity = Math.max(
      Number(this._socPlan?.capacity_kwh) || (energy.available ? energy.capacity : 0),
      ...past.map((point) => point[1]),
      ...planned.map((point) => point[1]),
      1,
    );
    const x = typeof geo.x === 'function'
      ? geo.x
      : (time) => geo.left + ((time - geo.from) / (geo.to - geo.from)) * (geo.right - geo.left);
    const y = (kwh) => geo.bottom - (Math.max(0, kwh) / capacity) * (geo.bottom - geo.top);
    const path = (points) => points.map((point, index) => `${index ? 'L' : 'M'}${x(point[0]).toFixed(1)},${y(point[1]).toFixed(1)}`).join('');
    const parts = [];
    if (past.length > 1) parts.push(`<path class="battery-soc__past" d="${path(past)}"></path>`);
    if (planned.length > 1) parts.push(`<path class="battery-soc__plan" d="${path(planned)}"></path>`);
    const label = (point, anchor, dx) => `<text class="battery-soc__label" x="${(x(point[0]) + dx).toFixed(1)}" y="${(y(point[1]) - 7).toFixed(1)}" text-anchor="${anchor}">${kwhFormat.format(point[1])} kWh</text>`;
    if (Number.isFinite(current) && now >= geo.from && now <= geo.to) {
      const working = this._batteryLevel?.dataset.flow === 'charge' || this._batteryLevel?.dataset.flow === 'discharge';
      if (working) parts.push(`<circle class="battery-soc__pulse" cx="${x(now).toFixed(1)}" cy="${y(current).toFixed(1)}" r="3.5"></circle>`);
      parts.push(`<circle class="battery-soc__dot" cx="${x(now).toFixed(1)}" cy="${y(current).toFixed(1)}" r="3.5"></circle>`);
      parts.push(label([now, current], 'start', 6));
    }
    const last = planned[planned.length - 1];
    if (last && x(last[0]) - x(now) > 90) parts.push(label(last, 'end', -2));
    const viewBox = `0 0 ${width} ${height}`;
    if (layer.getAttribute('viewBox') !== viewBox) layer.setAttribute('viewBox', viewBox);
    const markup = parts.join('');
    if (this._socMarkup !== markup) {
      this._socMarkup = markup;
      layer.innerHTML = markup;
    }
    if (this._socKey) this._socKey.hidden = parts.length === 0;
  }

  // The Nest Hub's font has no ⌀ (diameter sign) and shows a box; Ø looks alike and is there
  _fixGlyphs() {
    const root = this._chart?.shadowRoot;
    if (!this._kiosk || !root) return;
    for (const scope of root.querySelectorAll('.readout, .plot')) {
      const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (node.nodeValue.includes('⌀')) node.nodeValue = node.nodeValue.split('⌀').join('Ø');
      }
    }
  }

  // Dark from sunset to sunrise where night_mode is set, else as configured
  _applyAppearance(chart, force = false) {
    if (typeof chart?.setConfig !== 'function') return;
    const sun = this._hass?.states['sun.sun']?.state;
    const appearance = this._nightMode && sun === 'below_horizon' ? 'dark' : this._chartConfig.appearance;
    if (!force && appearance === this._appliedAppearance) return;
    this._appliedAppearance = appearance;
    chart.setConfig(appearance ? { ...this._chartConfig, appearance } : this._chartConfig);
  }

  async _ensureChart() {
    if (!this._chartSlot || this._chart) return;
    const chart = document.createElement(CHART_ELEMENT);
    this._chart = chart;
    this._chartSlot.append(chart);
    try {
      this._loadChartScript();
      await customElements.whenDefined(CHART_ELEMENT);
      if (this._chart !== chart) return;
      this._showStatus('');
      if (typeof chart.setConfig !== 'function') throw new Error('Die originale Tibber-Diagrammkarte wurde nicht geladen.');
      this._applyAppearance(chart, true);
      if (this._hass) {
        chart.hass = this._hass;
        await this._mountChartExtras(chart);
        await this._loadPlan(true);
      }
    } catch (error) {
      this._error.textContent = error?.message || 'Tibber-Diagramm konnte nicht geladen werden.';
      this._error.hidden = false;
    }
  }

  async _mountChartExtras(chart) {
    if (this._mountingExtras || !this._hass) return;
    this._mountingExtras = true;
    try {
      let seen = 'kein Shadow-DOM';
      for (let attempt = 0; attempt < 100; attempt += 1) {
        await new Promise((resolve) => {
          requestAnimationFrame(resolve);
          setTimeout(resolve, 100);
        });
        const root = chart.shadowRoot;
        const plotRegion = root?.querySelector('.chart');
        const plot = root?.querySelector('.plot');
        const card = root?.querySelector('ha-card');
        if (root) seen = `ha-card ${card ? 'ja' : 'nein'}, chart ${plotRegion ? 'ja' : 'nein'}, plot ${plot ? 'ja' : 'nein'}`;
        if (!plotRegion || !plot || !card) continue;

        if (!root.querySelector('[data-battery-phase-style]')) {
          const style = document.createElement('style');
          style.dataset.batteryPhaseStyle = 'true';
          style.textContent = `
            .battery-power{display:flex;flex-wrap:wrap;gap:10px clamp(14px,3cqw,40px);justify-content:space-between;margin:6px 16px 8px;padding:0 4px}
            .battery-tile{align-items:center;display:flex;gap:clamp(6px,1cqw,10px);min-width:0}
            .battery-tile[hidden]{display:none}
            .battery-tile ha-icon{--mdc-icon-size:clamp(22px,2.9cqw,30px);color:var(--disabled-text-color,#9e9e9e);flex:none;transition:color .4s ease}
            .battery-tile[data-key='battery'][data-state='charge'] ha-icon{color:var(--success-color,#43a047)}
            .battery-tile[data-key='battery'][data-state='discharge'] ha-icon{color:#3b78e7}
            .battery-tile[data-key='pv'][data-state='active'] ha-icon{color:#f5a623}
            .battery-tile[data-key='inverter'][data-state='active'] ha-icon{color:#36a879}
            .battery-tile[data-key='grid'][data-state='import'] ha-icon{color:var(--primary-text-color)}
            .battery-tile[data-key='grid'][data-state='export'] ha-icon{color:var(--success-color,#43a047)}
            .battery-tile[data-key='today'] ha-icon{color:var(--secondary-text-color)}
            .battery-tile__text{display:flex;flex-direction:column;gap:2px;min-width:0}
            .battery-tile__label{align-items:center;color:var(--secondary-text-color);display:flex;font-size:10px;font-size:clamp(10px,1.1cqw,12px);font-weight:600;gap:8px;letter-spacing:.06em;line-height:1.2;text-transform:uppercase;white-space:nowrap}
            .battery-tile__value{align-items:baseline;display:flex;gap:6px;line-height:1.1;white-space:nowrap}
            .battery-tile__value b,.battery-level__value{color:var(--primary-text-color);font-size:13px;font-size:clamp(13px,2.1cqw,22px);font-variant-numeric:tabular-nums;font-weight:600}
            .battery-power__value[data-active='false']{color:var(--secondary-text-color)}
            .battery-tile__sub{color:var(--secondary-text-color);font-size:11px;font-size:clamp(11px,1.35cqw,14px);font-variant-numeric:tabular-nums;font-weight:500}
            .battery-level__track{background:var(--divider-color);border-radius:4px;display:inline-block;flex:none;height:6px;height:clamp(6px,.7cqw,8px);overflow:hidden;position:relative;width:48px;width:clamp(48px,7cqw,90px)}
            .battery-level__fill{background-color:var(--success-color,#43a047);border-radius:4px;display:block;height:100%;transition:width .6s ease}
            .battery-level[data-flow='charge'] .battery-level__fill,.battery-level[data-flow='discharge'] .battery-level__fill{animation:battery-flow 1.4s linear infinite;background-image:repeating-linear-gradient(-45deg,rgba(255,255,255,.38) 0 4px,transparent 4px 9px);background-size:12.7px 100%}
            .battery-level[data-flow='discharge'] .battery-level__fill{animation-direction:reverse}
            @keyframes battery-flow{from{background-position:0 0}to{background-position:12.7px 0}}
            .battery-level__mark{background:var(--primary-text-color);height:100%;position:absolute;top:0;transform:translateX(-1px);width:2px}
            .battery-level__mark--reserve{background:var(--error-color,#db4437)}
            .battery-level__mark[hidden]{display:none}
            .battery-level[data-tone='warning'] .battery-level__fill{background-color:var(--warning-color,#f0a51b)}
            .battery-level[data-tone='low'] .battery-level__fill{background-color:var(--error-color,#db4437)}
            .battery-level[data-tone='unavailable'] .battery-level__value{color:var(--secondary-text-color)}
            ha-card[data-battery-kiosk]{border:0;border-radius:0;box-shadow:none}
            ha-card[data-battery-alert='warning']{box-shadow:inset 0 0 0 3px var(--warning-color,#f0a51b)}
            ha-card[data-battery-alert='error']{box-shadow:inset 0 0 0 3px var(--error-color,#db4437)}
            .battery-clock{flex:none;line-height:1;margin-left:auto;padding:2px 2px 0 12px;text-align:right}
            .battery-clock__time{color:var(--primary-text-color);font-size:44px;font-size:clamp(36px,7.5cqw,64px);font-variant-numeric:tabular-nums;font-weight:300;letter-spacing:-.02em}
            .battery-clock__date{color:var(--secondary-text-color);font-size:13px;font-size:clamp(13px,1.45cqw,15px);margin-top:6px;white-space:nowrap}
            .battery-clock__colon{animation:battery-colon 2s ease-in-out infinite;display:inline-block;margin:0 .02em;transform:translateY(-.06em)}
            @keyframes battery-colon{0%,100%{opacity:1}50%{opacity:.3}}
            .battery-clock__periods{display:flex;flex-direction:column;gap:3px;margin-top:6px}
            .battery-clock__period{align-items:center;color:var(--secondary-text-color);display:flex;font-size:12px;font-size:clamp(12px,1.3cqw,14px);gap:6px;justify-content:flex-end;white-space:nowrap}
            .battery-clock__period i{border-radius:50%;display:inline-block;height:8px;width:8px}
            .battery-clock__period[data-tone='good'] i{background:var(--success-color,#43a047)}
            .battery-clock__period[data-tone='bad'] i{background:var(--error-color,#db4437)}
            .battery-phase-lane{flex:none;padding:1px 0 5px}
            .battery-phase-head{align-items:center;display:flex;flex-wrap:wrap;gap:5px 10px;justify-content:space-between;margin:0 16px 5px;min-height:14px}
            .battery-phase-left{align-items:center;display:flex;flex-wrap:wrap;gap:4px 8px}
            .battery-phase-mode{background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:9px;color:var(--primary-text-color);font-size:11px;font-weight:600;padding:1px 8px}
            .battery-phase-mode[data-mode='versorgen']{background:color-mix(in srgb,#36a879 18%,transparent);border-color:#36a879}
            .battery-phase-mode[data-mode='netzladen']{background:color-mix(in srgb,#f0a51b 20%,transparent);border-color:#f0a51b}
            .battery-phase-mode[data-mode='sicher_aus']{background:color-mix(in srgb,var(--error-color,#db4437) 18%,transparent);border-color:var(--error-color,#db4437)}
            .battery-phase-mode[data-differs='true']{background:color-mix(in srgb,var(--warning-color,#f0a51b) 18%,transparent);border-color:var(--warning-color,#f0a51b)}
            .battery-phase-title{color:var(--secondary-text-color);font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase}
            .battery-phase-legend{align-items:center;display:flex;flex-wrap:wrap;gap:4px 9px}
            .battery-phase-key{align-items:center;color:var(--secondary-text-color);display:inline-flex;font-size:11px;gap:3px;white-space:nowrap}
            .battery-phase-swatch{border-radius:2px;display:inline-block;height:7px;width:12px}
            .battery-phase-track{background:repeating-linear-gradient(135deg,var(--secondary-background-color) 0 4px,var(--divider-color) 4px 5px);border-radius:4px;height:12px;height:clamp(10px,1.3cqw,14px);overflow:hidden;position:relative}
            .battery-phase-segment{border-radius:2px;height:100%;position:absolute;top:0}
            .battery-phase-segment.hold{background:#9299a1}
            .battery-phase-segment.charge{background:#f0a51b}
            .battery-phase-segment.serve{background:#36a879}
            .battery-phase-segment.conflict{background:repeating-linear-gradient(135deg,#d32f2f 0 4px,#ff8a80 4px 8px)}
            .battery-phase-now{background:var(--primary-text-color);height:100%;position:absolute;top:0;transform:translateX(-1px);width:2px}
            ha-card{--battery-soc-color:#3b78e7}
            ha-card[data-battery-dark]{--battery-soc-color:#7aa7f7}
            .battery-soc{height:100%;inset:0;overflow:visible;pointer-events:none;position:absolute;width:100%}
            .battery-soc__past,.battery-soc__plan{fill:none;stroke:var(--battery-soc-color);stroke-linecap:round;stroke-linejoin:round;stroke-width:2.2}
            .battery-soc__plan{opacity:.85;stroke-dasharray:6 5}
            .battery-soc__dot{fill:var(--battery-soc-color);stroke:var(--card-background-color,#fff);stroke-width:2}
            .battery-soc__pulse{animation:battery-soc-pulse 2.4s ease-out infinite;fill:var(--battery-soc-color);transform-box:fill-box;transform-origin:center}
            @keyframes battery-soc-pulse{from{opacity:.55;transform:scale(1)}to{opacity:0;transform:scale(3.4)}}
            .battery-soc__label{fill:var(--battery-soc-color);font-size:12px;font-weight:700;paint-order:stroke;stroke:var(--card-background-color,#fff);stroke-linejoin:round;stroke-width:3}
            ha-card[data-battery-dark] .battery-tile[data-key='battery'][data-state='discharge'] ha-icon{color:#7aa7f7}
            .battery-soc-swatch{background:repeating-linear-gradient(90deg,var(--battery-soc-color,#3b78e7) 0 5px,transparent 5px 7px);border-radius:1px;display:inline-block;height:3px;width:14px}
            .battery-phase-key[hidden]{display:none}
            .battery-phase-note{color:var(--secondary-text-color);font-size:11px;margin:3px 16px 0}
            .battery-phase-note:empty{display:none}
            @media (prefers-reduced-motion:reduce){.battery-clock__colon,.battery-soc__pulse,.battery-level__fill{animation:none!important}}
          `;
          root.append(style);
        }

        const readout = root.querySelector('.readout');
        let powerRow = root.querySelector('.battery-power');
        if (!powerRow) {
          powerRow = document.createElement('div');
          powerRow.className = 'battery-power';
          const tile = (key, icon, name, label = name, value = `<b class="battery-power__value" data-key="${key}" data-active="false">—</b>`) =>
            `<div class="battery-tile" data-key="${key}" data-state="idle"><ha-icon icon="${icon}"></ha-icon>`
            + `<div class="battery-tile__text"><div class="battery-tile__label">${label}</div><div class="battery-tile__value">${value}</div></div></div>`;
          const track = `<span class="battery-level__track" role="progressbar" aria-valuemin="0" aria-valuemax="100"><span class="battery-level__fill"></span>`
            + `<i class="battery-level__mark battery-level__mark--reserve"></i><i class="battery-level__mark battery-level__mark--target" hidden></i></span>`;
          powerRow.innerHTML = tile('battery', 'mdi:home-battery', 'Akku', `Akku ${track}`,
            `<b class="battery-level__value"></b><span class="battery-tile__sub battery-power__value" data-key="battery" data-active="false">—</span>`)
            + tile('pv', 'mdi:solar-power-variant', 'PV')
            + tile('inverter', 'mdi:current-ac', 'WR')
            + tile('grid', 'mdi:transmission-tower', 'Netz')
            + tile('today', 'mdi:home-import-outline', 'Heute', 'Heute',
              `<b class="battery-power__value" data-key="today" data-active="true">—</b><span class="battery-tile__sub battery-today-cost"></span>`);
          plotRegion.parentElement.insertBefore(powerRow, plotRegion);
        }
        const batteryLevel = powerRow.querySelector('.battery-tile[data-key="battery"]');
        batteryLevel.classList.add('battery-level');
        this._powerTiles = Object.fromEntries([...powerRow.querySelectorAll('.battery-tile')].map((element) => [element.dataset.key, element]));
        this._powerValues = Object.fromEntries([...powerRow.querySelectorAll('.battery-power__value')].map((element) => [element.dataset.key, element]));
        this._todayCost = powerRow.querySelector('.battery-today-cost');
        this._batteryLevel = batteryLevel;
        this._batteryLevelTrack = batteryLevel.querySelector('.battery-level__track');
        this._batteryLevelFill = batteryLevel.querySelector('.battery-level__fill');
        this._batteryLevelValue = batteryLevel.querySelector('.battery-level__value');
        this._markReserve = batteryLevel.querySelector('.battery-level__mark--reserve');
        this._markTarget = batteryLevel.querySelector('.battery-level__mark--target');
        this._haCard = card;
        if (this._kiosk) card.dataset.batteryKiosk = '';

        let lane = root.querySelector('.battery-phase-lane');
        if (!lane) {
          lane = document.createElement('div');
          lane.className = 'battery-phase-lane';
          lane.innerHTML = `<div class="battery-phase-head"><span class="battery-phase-left"><span class="battery-phase-title">Phasenplan</span><span class="battery-phase-mode" hidden></span></span><span class="battery-phase-legend"><span class="battery-phase-key"><i class="battery-phase-swatch" style="background:#9299a1"></i>Halten</span><span class="battery-phase-key"><i class="battery-phase-swatch" style="background:#f0a51b"></i>Netzladen</span><span class="battery-phase-key"><i class="battery-phase-swatch" style="background:#36a879"></i>WR-Freigabe</span><span class="battery-phase-key battery-soc-key" hidden><i class="battery-soc-swatch"></i>Akku kWh</span></span></div><div class="battery-phase-track"></div><div class="battery-phase-note"></div>`;
          const controls = root.querySelector('.controls');
          card.insertBefore(lane, controls || null);
        }
        this._phaseTrack = lane.querySelector('.battery-phase-track');
        this._phaseNote = lane.querySelector('.battery-phase-note');
        this._phaseTitle = lane.querySelector('.battery-phase-title');
        this._phaseMode = lane.querySelector('.battery-phase-mode');
        this._socKey = lane.querySelector('.battery-soc-key');

        let socLayer = plotRegion.querySelector('.battery-soc');
        if (!socLayer) {
          socLayer = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
          socLayer.setAttribute('class', 'battery-soc');
          socLayer.setAttribute('aria-hidden', 'true');
          plotRegion.insertBefore(socLayer, plotRegion.querySelector('.overlay'));
        }
        this._socLayer = socLayer;

        let clock = root.querySelector('.battery-clock');
        if (this._showClock && readout && !clock) {
          clock = document.createElement('div');
          clock.className = 'battery-clock';
          clock.innerHTML = '<div class="battery-clock__time"></div><div class="battery-clock__date"></div><div class="battery-clock__periods"></div>';
          readout.insertBefore(clock, readout.querySelector('.to-now'));
        }
        this._clockTime = clock?.querySelector('.battery-clock__time');
        this._clockDate = clock?.querySelector('.battery-clock__date');
        this._clockPeriods = clock?.querySelector('.battery-clock__periods');
        this._clockShown = undefined;

        if (!this._plotObserver) {
          this._plotObserver = new MutationObserver(() => {
            this._fixGlyphs();
            this._renderPhaseLane();
          });
        }
        this._plotObserver.disconnect();
        this._plotObserver.observe(plot, { childList: true });
        if (this._kiosk && readout) this._plotObserver.observe(readout, { childList: true, subtree: true, characterData: true });
        this._fixGlyphs();
        this._error.hidden = true;
        this._showStatus('');
        this._renderBatteryFill();
        this._renderPower();
        this._renderClock();
        this._renderPhaseLane();
        return;
      }
      throw new Error(`Plotbereich der Tibber-Karte wurde nicht gefunden (${seen}).`);
    } catch (error) {
      this._error.textContent = error?.message || 'Phasenanzeige konnte nicht in die Tibber-Karte gesetzt werden.';
      this._error.hidden = false;
      clearTimeout(this._remountTimer);
      this._remountTimer = setTimeout(() => {
        if (this._chart === chart && this.isConnected) this._mountChartExtras(chart);
      }, 5000);
    } finally {
      this._mountingExtras = false;
    }
  }

  async _loadPlan(force = false) {
    if (!this._hass?.callWS) return;
    if (this._planLoad) return this._planLoad;
    if (!force && Date.now() - (this._planLoadedAt || 0) < 30000) {
      this._renderPhaseLane();
      return;
    }
    const hass = this._hass;
    this._planLoad = (async () => {
      try {
        const schedules = await hass.callWS({ type: 'schedule/list' });
        this._phaseWindows = scheduleWindows(schedules, hass.config?.time_zone || 'UTC', this._planEntities);
        this._planError = '';
        this._planLoadedAt = Date.now();
      } catch (error) {
        this._phaseWindows = [];
        this._planError = 'Zeitplan nicht verfügbar';
        this._planLoadedAt = Date.now();
      } finally {
        this._renderPhaseLane();
        this._planLoad = null;
      }
    })();
    return this._planLoad;
  }

  _renderPhaseLane() {
    if (!this._phaseTrack || !this._hass || !this._chart) return;
    const geo = this._chart._geo;
    const plot = this._chart._els?.plot || this._chart.shadowRoot?.querySelector('.plot');
    const now = Date.now();
    const plan = this._planEntities;
    const expiry = Number(this._hass.states[plan.expiry]?.attributes?.timestamp) * 1000;
    const strategy = plan.strategy ? this._hass.states[plan.strategy]?.state : undefined;
    const plannerEnabled = this._hass.states[plan.permission]?.state === 'on';
    const timeZone = this._hass.config?.time_zone || 'UTC';
    const valid = Number.isFinite(expiry) && expiry > now && plannerEnabled && !INVALID_STRATEGIES.includes(strategy);
    this._renderSoc(geo, plot, now);
    const caption = phaseControlCaption(this._hass, valid, plan.owner);
    this._phaseTitle.textContent = caption.title;
    const regelmodus = plan.mode ? this._hass.states[plan.mode]?.state : undefined;
    const mode = currentModePresentation(regelmodus, this._phaseWindows, now, valid);
    this._phaseMode.hidden = !mode;
    if (mode) {
      this._phaseMode.textContent = `Jetzt: ${mode.label}`;
      this._phaseMode.title = mode.title;
      this._phaseMode.dataset.differs = String(mode.differs);
      this._phaseMode.dataset.mode = regelmodus;
    }
    if (this._haCard) {
      const dark = this._appliedAppearance === 'dark' || (this._appliedAppearance !== 'light' && Boolean(this._hass.themes?.darkMode));
      if (this._haCard.hasAttribute('data-battery-dark') !== dark) this._haCard.toggleAttribute('data-battery-dark', dark);
      const alert = regelmodus === 'sicher_aus' ? 'error'
        : regelmodus === 'reserve' || (plannerEnabled && !valid) ? 'warning' : '';
      if ((this._haCard.dataset.batteryAlert || '') !== alert) this._haCard.dataset.batteryAlert = alert;
    }

    if (this._planError) this._phaseNote.textContent = this._planError;
    else if (!valid) this._phaseNote.textContent = phaseInvalidReason({ plannerEnabled, expiry, now, strategy, timeZone });
    else if (!geo || !plot?.clientWidth) this._phaseNote.textContent = 'Zeitachse wird geladen';
    else this._phaseNote.textContent = '';

    this._phaseTrack.replaceChildren();
    if (!valid || this._planError || !geo || !plot?.clientWidth || geo.to <= geo.from) return;
    const trackWidth = geo.right - geo.left;
    if (trackWidth <= 0) return;
    this._phaseTrack.style.marginLeft = `${geo.left}px`;
    this._phaseTrack.style.marginRight = `${Math.max(0, plot.clientWidth - geo.right)}px`;
    const segments = buildPhaseSegments(this._phaseWindows, now, expiry, geo.from, geo.to, now);
    for (const segment of segments) {
      const element = document.createElement('span');
      element.className = `battery-phase-segment ${segment.mode}`;
      const left = ((segment.start - geo.from) / (geo.to - geo.from)) * 100;
      const width = ((segment.end - segment.start) / (geo.to - geo.from)) * 100;
      element.style.left = `${left}%`;
      element.style.width = `${width}%`;
      element.title = segmentTooltip(segment, now, timeZone);
      this._phaseTrack.append(element);
    }
    if (now > geo.from && now < geo.to) {
      const marker = document.createElement('span');
      marker.className = 'battery-phase-now';
      marker.style.left = `${((now - geo.from) / (geo.to - geo.from)) * 100}%`;
      marker.title = 'Jetzt';
      this._phaseTrack.append(marker);
    }
    if (segments.some((segment) => segment.mode === 'charge')) {
      const states = this._hass.states;
      const target = chargeTargetPresentation(
        states[this._batteryEntity]?.state,
        states[this._targetEntity]?.state,
        states[this._kwhEntity]?.state,
        this._capacityKwh,
      );
      if (target) this._phaseNote.textContent = `Netzladen: ${target.label}`;
    }
  }
}

if (typeof customElements !== 'undefined' && !customElements.get('tibber-prices-battery-chart-card')) {
  customElements.define('tibber-prices-battery-chart-card', TibberPricesBatteryChartCard);
}
if (typeof window !== 'undefined') {
  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === 'tibber-prices-battery-chart-card')) {
    window.customCards.push({
      type: 'tibber-prices-battery-chart-card',
      name: 'Hausakku-Planer: Tibber-Preise mit Akku',
      description: 'Tibber-Preiskurve mit Akku, veröffentlichtem Plan, Leistungen und Uhr (vom Hausakku-Planer-Add-on).',
      preview: false,
    });
  }
}
