// Lichtregie – Oberfläche. Drei Bereiche: Show (Startseite), Feinabstimmung (während der Party), Einrichten
// (einmal einstellen, Technik und Fehlersuche).
const $ = id => document.getElementById(id);
const all = sel => Array.from(document.querySelectorAll(sel));
const timers = {};
let state = {}, settings = {}, status = {};

function api(path, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'},
                                         body: JSON.stringify(body)};
  return fetch(path, opt).then(r => r.json());
}
function throttled(key, fn) { clearTimeout(timers[key]); timers[key] = setTimeout(fn, 60); }
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

// --- Bereiche ---------------------------------------------------------------------------------------
function showTab(name) {
  for (const b of all('#tabs button')) b.classList.toggle('on', b.dataset.tab === name);
  for (const m of all('main')) m.hidden = m.id !== 'tab-' + name;
  try { localStorage.setItem('tab', name); } catch (e) { /* ohne Speicher: Startseite */ }
  resize();
}
for (const b of all('#tabs button')) b.addEventListener('click', () => showTab(b.dataset.tab));

// --- Einstellungen: Schalter und Regler tragen data-set="name" ----------------------------------------
function setSetting(body) { api('api/settings', body).then(s => { settings = s; showSettings(); }); }
for (const el of all('button[data-set]')) el.addEventListener('click', () => setSetting({[el.dataset.set]: !settings[el.dataset.set]}));
for (const el of all('button[data-choice]')) el.addEventListener('click', () => setSetting({[el.dataset.choice]: +el.dataset.value}));
for (const el of all('input[data-set]')) {
  el.addEventListener('input', () => showValue(el.dataset.set, +el.value));
  el.addEventListener('change', () => setSetting({[el.dataset.set]: +el.value}));
}
function showValue(key, v) {
  for (const el of all(`[data-val="${key}"]`)) {
    const unit = el.dataset.unit === ' Schläge' && +v === 1 ? ' Schlag' : (el.dataset.unit || '');
    el.textContent = (+v).toLocaleString('de-DE') + unit;      // 0,35 s statt 0.35 s
  }
}
function showSettings() {
  for (const el of all('button[data-set]')) el.classList.toggle('on', !!settings[el.dataset.set]);
  for (const el of all('button[data-choice]')) el.classList.toggle('on', settings[el.dataset.choice] === +el.dataset.value);
  for (const el of all('input[data-set]')) {
    if (document.activeElement !== el) el.value = settings[el.dataset.set];
    showValue(el.dataset.set, settings[el.dataset.set]);
  }
  // Dauer-Regler nur, wenn Blinder bzw. Flash an sind
  for (const [key, on] of [['tv_blinder_lang', settings.tv_blinder > 0], ['tv_blinder_hell', settings.tv_blinder > 0],
                           ['tv_flash_lang', settings.tv_flash > 0], ['tv_flash_hell', settings.tv_flash > 0]]) {
    const el = document.querySelector(`input[data-set="${key}"]`);
    if (el) { el.disabled = !on; el.closest('label').classList.toggle('off', !on); }
  }
}

// --- Startseite: Party, Lied, Status -------------------------------------------------------------------
const RADFARBE = {0: '#ffffff', 17: '#ff3b30', 22: '#34c759', 36: '#3a6bff', 44: '#ffd60a',
  54: '#ff9500', 64: '#7fdcff', 73: '#bf5af2'};
$('party').addEventListener('click', () => {
  const an = !(status.party && status.party.an);
  $('party').textContent = an ? 'startet …' : 'stoppt …';
  api('api/party', {an}).then(showStatus);
});
$('wuerfeln').addEventListener('click', () => api('api/wuerfeln', {}));
$('neustart').addEventListener('click', () => api('api/geraete_neustart', {}));

function minutes(sec) { return sec >= 90 ? Math.round(sec / 60) + ' min' : sec + ' s'; }
function partyText(p) {
  if (p.an) {
    let t = 'Party läuft (' + p.grund + ')';
    if (p.aus_in !== null) t += ' · keine Musik, aus in ' + minutes(p.aus_in);
    return t;
  }
  if (p.gesperrt) return 'Von Hand gestoppt. Die Automatik wartet, bis die Musik eine Minute aus war.';
  if (!p.automatik) return 'Aus. Automatik ist abgeschaltet.';
  return p.musik ? 'Musik erkannt, startet …' : 'Aus. Startet von selbst, sobald Musik ankommt.';
}
function tile(name, value, level) {
  return `<div class="tile ${level}"><div class="k">${esc(name)}</div><div class="v">${esc(value)}</div></div>`;
}
function deviceTiles(p) {
  return p.geraete.map(g => tile(g.name, g.zustand === 'on' ? 'an' : g.zustand === 'off' ? 'aus' : 'unbekannt',
    g.zustand === 'on' ? 'ok' : g.zustand === 'off' ? '' : 'warn')).join('');
}
function audioTile(a) {
  if (!a) return tile('Audio', 'nicht eingerichtet', '');
  if (!settings.audio) return tile('Audio', 'abgeschaltet', '');
  if (!a.an) return tile('Audio', a.stumm ? 'Daten, aber stumm' : 'kein Signal', status.party.an && status.spielt ? 'bad' : '');
  return a.takt ? tile('Audio', `Takt sitzt · ${a.bpm} BPM`, 'ok') : tile('Audio', 'sucht den Takt', 'warn');
}
function showStatus(d) {
  status = d;
  const p = d.party;
  $('party').textContent = p.an ? 'Party stoppen' : 'Party starten';
  $('party').classList.toggle('an', p.an);
  $('hero').classList.toggle('an', p.an);
  $('partystat').textContent = partyText(p);
  $('einrichtenhint').hidden = !p.an;
  const devs = p.an && p.geraete.length > 0;
  $('neustart').hidden = $('neustarthint').hidden = !devs;
  $('neustart').disabled = p.hochfahren > 0;
  $('neustart').textContent = p.hochfahren > 0 ? `Geräte fahren hoch … ${p.hochfahren} s` : 'Geräte neu starten';
  $('warnungen').innerHTML = d.warnungen.map(w => `<p class="warn">⚠ ${esc(w)}</p>`).join('');
  // Lied
  const l = d.lied;
  $('titel').textContent = l ? l.titel + (l.interpret ? ' – ' + l.interpret : '') : (d.titel || 'Kein Lied');
  $('szene').textContent = d.szene || (l ? '' : (p.an ? d.info : '–'));
  $('wuerfeln').hidden = !l;
  $('chips').innerHTML = !l ? '' : [
    `${l.bpm} BPM${l.tempo_quelle === 'Audio' ? ' (aus dem Audio)' : ''}`, l.stufe,
    `<b style="background:${RADFARBE[l.farben[0]]}"></b><b style="background:${RADFARBE[l.farben[1]]}"></b>${esc(l.farbnamen.join(' / '))}`,
    'Gobos ' + esc(l.gobos.join(' / ')), 'Laser ' + esc(l.laser),
    `Lampen alle ${settings.lampen_wechsel > 0 ? Math.max(2, settings.lampen_wechsel / 4) : l.lampen_takte} Takte`,
    l.variante ? 'Thema ' + (l.variante + 1) : ''].filter(Boolean).map(c => `<span class="chip">${c}</span>`).join('');
  // Kacheln
  const a = d.audio;
  $('tiles').innerHTML = audioTile(a)
    + tile('Lied', d.titel ? (d.spielt ? 'spielt' : 'pausiert') : 'kein Titel', d.titel ? (d.spielt ? 'ok' : 'warn') : (p.an ? 'bad' : ''))
    + deviceTiles(p)
    + tile('Lampen', settings.lampen ? (p.an ? 'folgen der Show' : 'bereit') : 'abgeschaltet', settings.lampen && p.an ? 'ok' : '')
    + tile('Laser', settings.laser ? (l ? l.laser : 'bereit') : 'aus', settings.laser && l && l.laser !== 'aus' ? 'ok' : '');
  $('audiostat').textContent = !a ? 'Audio: nicht eingerichtet (Add-on-Option AirPlay)'
    : a.an ? `${a.takt ? 'Takt eingerastet' : 'sucht den Takt'} · ${a.bpm || '–'} BPM · Sicherheit ${Math.round(a.sicher * 100)} % · Pegel ${Math.round(a.pegel * 100)} %`
             + (a.break ? ' · Break' : '') + (a.drop ? ' · Drop' : '') + (a.wechsel ? ' · Phrasenwechsel' : '')
    : 'Kein Signal am Empfänger';
  $('technikstat').textContent = technikText(d);
  const ls = d.lampen;
  $('lampstat').textContent = !ls ? 'Lampen: in der letzten Minute keine Befehle'
    : `Letzte Minute: ${ls.befehle_min} Befehle (Ambilights ${ls.ambilight_min}) · Dauer ${ls.dauer_ms} ms,`
      + ` höchstens ${ls.max_ms} ms` + (ls.fehler ? ` · ${ls.fehler} fehlgeschlagen` : ' · keine Fehler')
      + (ls.tv_min ? ` · LED-Streifen ${ls.tv_min} Befehle, je ${ls.tv_ms} ms` : '');
  const r = d.aufnahme;
  if (r) {
    $('recstat').textContent = r.laeuft ? `Aufnahme läuft, noch ${r.rest} s · ${r.marken} × „1“, ${r.haenger} × hängt` + (r.ton ? '' : ' · kein Ton!')
      : 'Keine Aufnahme läuft.';
    $('recstart').textContent = r.laeuft ? 'Aufnahme beenden' : 'Aufnahme starten (90 s)';
    $('recstart').dataset.an = r.laeuft ? '1' : '';
    $('recmark').disabled = !r.laeuft;
    $('rechang').disabled = !r.laeuft;
    const list = r.dateien.map(n => `<a href="aufnahme/${esc(n)}" download>${esc(n)}</a>`).join(' · ');
    if ($('recfiles').dataset.list !== list) { $('recfiles').dataset.list = list; $('recfiles').innerHTML = list ? 'Herunterladen: ' + list : ''; }
  }
  spots = d.spots || {};
  showSync(d.sync);
  draw();
}
// --- Schlaganzeige: zählt im Browser im Takt weiter ---------------------------------------------------
// Bis 0.9.16 sprang sie nur bei jeder Abfrage (alle 200 ms plus Laufzeit über HA) und las den Schlag aus dem
// Szenentext: Bei 130 BPM (460 ms je Schlag) kamen die Punkte zu spät oder wurden übersprungen.
let beatClock = null;            // {b, bpm, at: performance.now() zu b, pause}
function syncClock(s, t0, t1) {
  if (!s || s.schlag_nr == null || !s.bpm) { beatClock = null; return; }
  const at = (t0 + t1) / 2;                       // das Gerät hat den Schlag etwa zur Mitte der Abfrage gemeldet
  const fresh = {b: s.schlag_nr, bpm: s.bpm, at, pause: !!s.pause};
  if (beatClock && !fresh.pause && !beatClock.pause && beatClock.bpm === fresh.bpm) {
    // kleine Abweichungen (Laufzeit schwankt) sanft einziehen, große (Korrektur, Spulen) sofort übernehmen
    const pred = beatAt(beatClock, at);
    const err = fresh.b - pred;
    if (Math.abs(err) < 0.3) { fresh.b = pred + 0.3 * err; }
  }
  beatClock = fresh;
}
function beatAt(c, now) { return c.pause ? c.b : c.b + (now - c.at) / 1000 * c.bpm / 60; }
function beatLoop() {
  const now = performance.now();
  const b = beatClock ? beatAt(beatClock, now) : null;
  const beat = b == null ? -1 : ((Math.floor(b) % 4) + 4) % 4;
  const bar = b == null ? -1 : ((Math.floor(b / 4) % 8) + 8) % 8;
  all('#beat i').forEach((el, i) => { el.classList.toggle('on', i === beat); el.classList.toggle('eins', i === 0); });
  all('#phrase .bar').forEach((el, bi) => {
    el.classList.toggle('cur', bi === bar);
    el.querySelectorAll('i').forEach((dot, di) => { dot.classList.toggle('on', bi === bar && di === beat); dot.classList.toggle('eins', di === 0); });
  });
}

// --- Takt-Sync: 8 Takte à 4 Schläge, aktueller Schlag leuchtet ---------------------------------------
$('phrase').innerHTML = Array.from({length: 8}, (_, i) => `<div class="bar${i === 0 ? ' first' : ''}"><i></i><i></i><i></i><i></i></div>`).join('');
// Technik: Bildrate der Show, Lücken beim Senden, Beat This, Eingangsrate des Tons
function technikText(d) {
  const parts = [];
  if (d.fps) parts.push(`Show ${d.fps} Bilder/s` + (d.fps < 25 ? ' (zu wenig, Soll 40)' : ''));
  if (d.bilder) parts.push(`größte Lücke der Show ${d.bilder.max_ms} ms`);
  const sd = d.senden;
  if (sd) {
    const lost = Object.entries(sd.verworfen || {}).map(([n, c]) => `${n}: ${c}`).join(', ');
    parts.push(`Senden ${sd.fps}/s, größte Lücke ${sd.max_ms} ms, ${sd.ruckler} Ruckler in 10 s` + (lost ? ` · verworfen ${lost}` : ''));
  } else parts.push('Art-Net: sendet nicht (Party aus)');
  const b = d.beatthis;
  if (b && b.rechenzeit != null) parts.push(`Beat This: ${b.schlaege} Schläge in ${b.rechenzeit} s gerechnet (vor ${b.vor_s} s)`
    + (b.bpm ? `, ${b.bpm} BPM` : ''));
  if (b && b.fehler) parts.push(`Beat This Fehler: ${b.fehler}`);
  const ap = d.airplay;
  if (ap) parts.push(ap.eintraege ? `AirPlay: ${ap.titel || 'kein Titel'}` + (ap.position != null ? ` bei ${ap.position} s` + (ap.dauer ? ` von ${ap.dauer} s` : '') : ', keine Position')
      + (ap.zeitmarke ? ', Zeitmarken' : '') + ` (${ap.eintraege} Einträge)` : 'AirPlay: noch keine Metadaten');
  if (d.audio && d.audio.eingang != null) parts.push(`Ton kommt mit ${d.audio.eingang}× Echtzeit an`);
  return parts.join(' · ') || '–';
}
function showSync(s) {
  $('syncstat').textContent = !s ? 'Keine Show läuft.'
    : `Phrase ${s.phrase} · Takt ${s.takt} von 8 · Schlag ${s.schlag} · ` + (s.audio ? 'Takt vom Audio' : 'Takt aus der Liedposition')
      + (s.eins ? ' · „1“ ' + (s.eins.quelle === 'Beat This' ? `von Beat This (${Math.round(s.eins.deutlich * 100)} % einig)`
                               : s.eins.quelle === 'von Hand' ? 'von Hand gesetzt'
                               : s.eins.quelle === 'gespeichert' ? 'aus dem Speicher (vom letzten Abspielen)'
                               : 'geschätzt, Beat This rechnet noch') : '')
      + (s.ereignisse.length ? ' · ' + s.ereignisse.join(', ') : '');
}
for (const [id, body] of [['syncm4', {schlaege: -4}], ['syncp4', {schlaege: 4}], ['syncm1', {schlaege: -1}],
                          ['syncp1', {schlaege: 1}], ['eins', {eins: 4}], ['einsphrase', {eins: 32}]]) {
  $(id).addEventListener('click', () => api('api/sync', body));
}

$('recstart').addEventListener('click', () => api('api/aufnahme', {an: !$('recstart').dataset.an}));
$('recmark').addEventListener('click', () => api('api/aufnahme', {marke: true}));
$('rechang').addEventListener('click', () => api('api/aufnahme', {haenger: true}));

// --- Raumbild: aus Sicht der Kopfwand (y = 6), leicht von oben, Blick Richtung TV-Wand ----------------
const CAM = {pos: [2.5, 5.9, 2.2], target: [2.5, 0, 0.8], fov: 62 * Math.PI / 180};
const BOX = {min: [0, 0, 0], max: [5, 6, 2.5]};
const FACE = ['Seitenwand', 'TV-Wand bzw. Kopfwand', 'Boden bzw. Decke'];
let padXY = null, spots = {};
let W = 300, H = 225;
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = a => { const l = Math.hypot(a[0], a[1], a[2]); return [a[0] / l, a[1] / l, a[2] / l]; };


function basis() {
  const f = norm(sub(CAM.target, CAM.pos));
  const r = norm(cross(f, [0, 0, 1]));
  return {f, r, u: cross(r, f)};
}
// Raumpunkt -> Bildanteile (0..1), null wenn hinter der Kamera
function project(P) {
  const B = basis(), v = sub(P, CAM.pos), zc = dot(v, B.f);
  if (zc <= 0.01) return null;
  const h = Math.tan(CAM.fov / 2), aspect = W / H;
  return [0.5 + dot(v, B.r) / zc / (2 * h * aspect), 0.5 - dot(v, B.u) / zc / (2 * h)];
}
// Bildanteile -> Fläche des Raums, auf die der Strahl trifft (Kamera steht im Raum)
function pick(fu, fv) {
  const B = basis(), h = Math.tan(CAM.fov / 2), aspect = W / H;
  const d = add(add(B.f, scale(B.r, (fu - 0.5) * 2 * h * aspect)), scale(B.u, (0.5 - fv) * 2 * h));
  let t = Infinity, axis = 0;
  for (let i = 0; i < 3; i++) {
    let ti = null;
    if (d[i] > 1e-9) ti = (BOX.max[i] - CAM.pos[i]) / d[i];
    else if (d[i] < -1e-9) ti = (BOX.min[i] - CAM.pos[i]) / d[i];
    if (ti !== null && ti > 0 && ti < t) { t = ti; axis = i; }
  }
  const P = add(CAM.pos, scale(d, t));
  for (let i = 0; i < 3; i++) P[i] = Math.min(BOX.max[i], Math.max(BOX.min[i], P[i]));
  return {P, face: axis};
}
function drawRoom(canvas, withSpots, target) {
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);
  const corners = [];
  for (const x of [0, 5]) for (const y of [0, 6]) for (const z of [0, 2.5]) corners.push([x, y, z]);
  ctx.strokeStyle = '#4a4a52'; ctx.lineWidth = 1.5;
  for (let i = 0; i < corners.length; i++) for (let j = i + 1; j < corners.length; j++) {
    const a = corners[i], b = corners[j];
    if ([0, 1, 2].filter(k => a[k] !== b[k]).length !== 1) continue;
    const pa = project(a), pb = project(b);
    if (!pa || !pb) continue;
    ctx.beginPath(); ctx.moveTo(pa[0] * W, pa[1] * H); ctx.lineTo(pb[0] * W, pb[1] * H); ctx.stroke();
  }
  // TV (ca. 1,2 m breit, Mitte 2,5 m, Höhe 0,5 bis 1,3 m)
  const tv = [[1.9, 0, 0.5], [3.1, 0, 0.5], [3.1, 0, 1.3], [1.9, 0, 1.3]].map(project);
  if (tv.every(p => p)) {
    ctx.fillStyle = '#1b2a3a'; ctx.beginPath();
    tv.forEach((p, i) => i ? ctx.lineTo(p[0] * W, p[1] * H) : ctx.moveTo(p[0] * W, p[1] * H));
    ctx.closePath(); ctx.fill();
  }
  // Spots der laufenden Show, in der Farbe des Farbrads, Deckkraft nach Helligkeit
  for (const k of withSpots ? ['1', '2'] : []) {
    const s = spots[k];
    const p = s && project([s.x, s.y, s.z]);
    if (!p) continue;
    ctx.globalAlpha = s.hell > 0 ? 0.25 + 0.75 * s.hell / 255 : 0.08;
    ctx.fillStyle = RADFARBE[s.farbe] || '#ffffff';
    ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 20;
    ctx.beginPath(); ctx.arc(p[0] * W, p[1] * H, 13, 0, 2 * Math.PI); ctx.fill();
    ctx.shadowBlur = 0; ctx.globalAlpha = 1;
    ctx.fillStyle = '#000'; ctx.font = '11px sans-serif'; ctx.fillText(k, p[0] * W - 3, p[1] * H + 4);
  }
  const c = target && project([target.x, target.y, target.z]);
  if (c) {
    ctx.fillStyle = '#0a84ff'; ctx.shadowColor = '#0a84ff'; ctx.shadowBlur = 16;
    ctx.beginPath(); ctx.arc(c[0] * W, c[1] * H, 9, 0, 2 * Math.PI); ctx.fill();
    ctx.shadowBlur = 0;
  }
}
function draw() {
  if (!$('tab-show').hidden) drawRoom($('preview'), true, null);
  if (!$('tab-einrichten').hidden) drawRoom($('room'), true, padXY);
}
function resize() {
  const visible = [$('preview'), $('room')].find(c => c.offsetParent !== null);
  if (!visible) return;
  W = Math.max(240, Math.min(520, Math.round(visible.clientWidth))); H = Math.round(W * 0.75);
  const dpr = window.devicePixelRatio || 1;
  for (const c of [$('preview'), $('room')]) {
    c.style.height = H + 'px'; c.width = W * dpr; c.height = H * dpr;
    c.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  draw();
}
window.addEventListener('resize', resize);

// --- Einrichten: Raum antippen ------------------------------------------------------------------------
let lastSend = 0, pendingTimer = null;
// Das Kalibriermodell (geometry.py) hat die x-Achse gespiegelt gegenüber dem Raum, deshalb 5 − x
function sendTarget() { api('api/target', {x: 5 - padXY.x, y: padXY.y, z: padXY.z}).then(s => { state = s; showHeads(); }); }
function touchRoom(e) {
  const r = $('room').getBoundingClientRect();
  const fu = (e.clientX - r.left) / r.width, fv = (e.clientY - r.top) / r.height;
  const {P, face} = pick(Math.min(1, Math.max(0, fu)), Math.min(1, Math.max(0, fv)));
  padXY = {x: P[0], y: P[1], z: P[2]};
  $('coords').textContent = `x ${P[0].toFixed(2)} m, y ${P[1].toFixed(2)} m, z ${P[2].toFixed(2)} m · ${FACE[face]}`;
  draw();
  const now = Date.now();
  if (now - lastSend >= 50) { lastSend = now; sendTarget(); }
  else { clearTimeout(pendingTimer); pendingTimer = setTimeout(() => { lastSend = Date.now(); sendTarget(); }, 50); }
}
$('room').addEventListener('pointerdown', e => { $('room').setPointerCapture(e.pointerId); touchRoom(e); });
$('room').addEventListener('pointermove', e => { if ($('room').hasPointerCapture(e.pointerId)) touchRoom(e); });
$('room').addEventListener('pointerup', e => { $('room').releasePointerCapture(e.pointerId); });
$('save').addEventListener('click', () => api('api/save', {}).then(s => {
  $('coords').textContent = `gemerkt: Nr. ${s.count} (${s.ziel ? 'Ziel ' + s.ziel.x.toFixed(2) + ' / ' + s.ziel.y.toFixed(2) + ' / ' + s.ziel.z.toFixed(2) : 'ohne Zielpunkt'})`;
}));

// --- Einrichten: Köpfe von Hand -----------------------------------------------------------------------
// Farbtabelle Farbrad-Kanal (Beobachtung am Gerät): Startwert je Farbe, darüber gilt der Bereich
const FARBEN = [[0, 'weiß'], [17, 'rot'], [22, 'grün'], [36, 'blau'], [44, 'gelb'], [54, 'orange'],
  [64, 'eisblau'], [73, 'lila'], [85, 'eisblau/lila'], [93, 'eisblau/orange'], [101, 'orange/gelb'],
  [113, 'gelb/blau'], [121, 'grün/blau'], [132, 'grün/rot']];
function farbName(v) {
  if (v >= 140) return 'Auto-Programm';
  let name = 'weiß';
  for (const [start, n] of FARBEN) if (v >= start) name = n;
  return name;
}
// Gobo-Muster (Beobachtung am Gerät): Startwert je Muster
const GOBOS = [[0, 'voll offen'], [13, 'Atom-Ring'], [21, 'Punkte-Ring'], [27, 'Punkte-Blume'], [34, 'grobe Löcher'],
  [43, 'Blubberblasen'], [50, 'Swirl'], [57, 'Striche'], [58, 'unbekannt'],
  // Zittern: je Muster drei Stufen, langsam bis schnell (nur Atom ist bestätigt, die anderen angenommen)
  [73, 'Atom zittern langsam'], [74, 'Atom zittern mittel'], [76, 'Atom zittern schnell'],
  [80, 'Punkte-Ring zittern 1'], [82, 'Punkte-Ring zittern 2'], [85, 'Punkte-Ring zittern 3'],
  [89, 'Punkte-Blume zittern 1'], [90, 'Punkte-Blume zittern 2'], [93, 'Punkte-Blume zittern 3'],
  [97, 'grobe Löcher zittern 1'], [99, 'grobe Löcher zittern 2'], [100, 'grobe Löcher zittern 3'],
  [105, 'Blasen zittern 1'], [108, 'Blasen zittern 2'], [111, 'Blasen zittern 3'],
  [113, 'Swirl zittern 1'], [115, 'Swirl zittern 2'], [117, 'Swirl zittern 3'],
  [121, 'Striche zittern 1'], [123, 'Striche zittern 2'], [126, 'Striche zittern 3']];
const GOBO_SCHNELL = GOBOS.map(([v, n]) => [n, v]);
function goboName(v) {
  let name = 'voll offen';
  for (const [start, n] of GOBOS) if (v >= start) name = n;
  return name;
}
// Strobe (Beobachtung am Gerät): 0 und 255 = Licht dauerhaft an, dazwischen blinkt es, je höher desto schneller
function strobeName(v) {
  if (v === 0 || v === 255) return 'kein Strobe (an)';
  return v === 200 ? 'Strobe, guter Wert' : 'Strobe, schneller je höher';
}
const SCHNELL = [['weiß', 0], ['rot', 17], ['grün', 22], ['blau', 36], ['gelb', 44], ['orange', 54], ['eisblau', 64], ['lila', 73]];
const MISCH = [['eisblau/lila', 85], ['eisblau/orange', 93], ['orange/gelb', 101], ['gelb/blau', 113], ['grün/blau', 121], ['grün/rot', 132]];

// Regler je Kopf: [Kürzel, Name, Kanal im Zustand, Maximum, Anzeige]
const HEAD_SLIDERS = [['p', 'Pan', 'pan', 65535, v => v], ['t', 'Tilt', 'tilt', 65535, v => v],
  ['h', 'Helligkeit', 'hell', 255, v => v], ['f', 'Farbe', 'farbe', 255, v => v + ' · ' + farbName(v)],
  ['g', 'Gobo', 'gobo', 255, v => v + ' · ' + goboName(v)], ['s', 'Strobe', 'strobe', 255, v => v + ' · ' + strobeName(v)]];
function setHead(k, values) { api('api/set', {heads: {[k]: values}}).then(s => { state = s; showHeads(); }); }
function presetButtons(list) { return list.map(([n, v]) => `<button data-v="${v}">${n}</button>`).join(''); }
function buildHeads() {
  $('heads').innerHTML = [1, 2].map(k => `<section class="card"><h2>Kopf ${k}</h2>`
    + HEAD_SLIDERS.map(([id, name, , max]) => `<label>${name} <span class="val" id="${id}v${k}"></span>
        <input type="range" min="0" max="${max}" id="${id}${k}"></label>`
        + (id === 'f' ? `<div class="presets" id="pr${k}">${presetButtons(SCHNELL.concat(MISCH))}</div>` : '')
        + (id === 'g' ? `<div class="presets" id="gp${k}">${presetButtons(GOBO_SCHNELL)}</div>` : '')).join('')
    + `<p class="hint">Strobe ist Blitzlicht: nur kurz testen.</p><button id="b${k}"></button></section>`).join('');
  for (const k of [1, 2]) {
    for (const [id, , key] of HEAD_SLIDERS) {
      $(id + k).addEventListener('input', () => throttled(id + k, () => setHead(k, {[key]: +$(id + k).value})));
    }
    for (const b of all(`#pr${k} button`)) b.addEventListener('click', () => setHead(k, {farbe: +b.dataset.v}));
    for (const b of all(`#gp${k} button`)) b.addEventListener('click', () => setHead(k, {gobo: +b.dataset.v}));
    $('b' + k).addEventListener('click', () => setHead(k, {on: !state[k].on}));
  }
}
function showHeads() {
  for (const k of [1, 2]) {
    const s = state[k];
    if (!s) continue;
    for (const [id, , key, , text] of HEAD_SLIDERS) {
      if (document.activeElement !== $(id + k)) $(id + k).value = s[key];
      $(id + 'v' + k).textContent = text(s[key]);
    }
    $('b' + k).textContent = s.on ? `Kopf ${k} dunkel` : `Kopf ${k} hell`;
  }
}
for (const k of [1, 2]) $('kugel' + k).addEventListener('click', () => api('api/kugel', {kopf: k}).then(s => { settings = s; loadState(); }));
$('kugelaus').addEventListener('click', () => setSetting({kugel_kopf: 0}));
$('allon').addEventListener('click', () => api('api/set', {heads: {1: {on: true}, 2: {on: true}}}).then(s => { state = s; showHeads(); }));
$('alloff').addEventListener('click', () => api('api/set', {heads: {1: {on: false}, 2: {on: false}}}).then(s => { state = s; showHeads(); }));

// --- Einrichten: Laser von Hand ------------------------------------------------------------------------
const LASER = [['mode', 'Modus'], ['shape', 'Form'], ['rotate', 'Rotation'], ['mirror_h', 'Spiegel waagerecht'],
  ['mirror_v', 'Spiegel senkrecht'], ['up_down', 'Hoch/runter'], ['left_right', 'Links/rechts'], ['size', 'Größe'],
  ['color', 'Farbe'], ['dots', 'Punkte-Geschwindigkeit']];
const LSHAPES = [[0, 'Quadrat'], [8, 'Kreis'], [13, 'senkrechter Strich'], [17, 'waagerechter Strich'],
  [21, 'Diagonale'], [27, 'Halbkreis unten'], [34, 'Halbkreis links'], [37, 'Dreieck'], [43, 'V-Form'],
  [48, 'zwei senkrechte Striche'], [52, 'zwei waagerechte Striche'], [59, 'senkrecht mit Lücke'],
  [64, 'waagerecht mit Lücke'], [67, 'Welle'], [73, 'invertierte Welle'], [79, 'Musiknote'],
  [82, 'Kreis rechts oben'], [87, 'Tannenbaum'], [92, 'Zahl 3'], [96, '<'], [102, 'Stern'],
  [108, 'senkrechte Welle'], [113, 'Zahl 2'], [116, 'Zahl 1'], [122, 'Herz'], [128, 'Punkte in den Ecken'],
  [132, 'Apfel'], [136, 'gestrichelter Kreis'], [142, 'zwei Kreise'], [148, 'Doppelkreis'],
  [152, 'Fluxkompensator'], [156, 'Plus'], [162, 'Kreis mit Quadrat'], [167, 'Doppeldreieck'],
  [172, 'Striche-Swirl'], [176, 'drei Striche'], [181, 'drei versetzte Striche'], [187, 'Fünfeck'],
  [191, 'Fadenkreuz'], [196, 'D-Pad'], [201, 'Pfeil'], [207, 'Unendlich'], [212, 'Wurfstern'],
  [216, 'seltsames Dreieck'], [222, 'Quadrat auf Spitze'], [226, 'Dreieck mit Pfeil'], [231, 'Sims-Kristall'],
  [238, 'Fliege']];
function laserShapeName(v) {
  let n = '';
  for (const [st, name] of LSHAPES) if (v >= st) n = name;
  return n;
}
let laserPower = false;
function buildLaser() {
  $('lsliders').innerHTML = LASER.map(([k, n]) => `<label>${n} <span class="val" id="lzv_${k}"></span>
    <input type="range" min="0" max="255" id="lz_${k}"></label>`).join('');
  for (const [k] of LASER) {
    $('lz_' + k).addEventListener('input', () => throttled('lz' + k,
      () => api('api/laser', {values: {[k]: +$('lz_' + k).value}}).then(showLaser)));
  }
  $('lPreset').addEventListener('click', () => api('api/laser', {preset: true}).then(showLaser));
  $('lPower').addEventListener('click', () => {
    laserPower = !laserPower;
    api('api/laser_power', {on: laserPower}).then(d => {
      $('lmsg').textContent = d.ok ? (laserPower ? 'Steckdose an, der Laser braucht ca. 20 s' : 'Steckdose aus')
                                   : 'Keine Steckdose eingestellt (Add-on-Option „Laser-Steckdose“)';
      $('lPower').textContent = laserPower ? 'Steckdose aus' : 'Steckdose an';
    });
  });
}
function showLaser(l) {
  if (!l) return;
  for (const [k] of LASER) {
    if (document.activeElement !== $('lz_' + k)) $('lz_' + k).value = l.werte[k];
    const sent = l.gesendet[k];
    $('lzv_' + k).textContent = l.werte[k] + (k === 'shape' ? ' · ' + laserShapeName(l.werte[k]) : '')
      + (sent !== l.werte[k] ? ` → ${sent} (Grenze)` : '');
  }
}

// --- Start und Abfragen --------------------------------------------------------------------------------
function loadState() {
  return api('api/state').then(s => {
    state = s; settings = s.settings;
    $('ledcard').hidden = !s.led;                  // Karte nur mit eingetragenem LED-Streifen
    $('kugelcard').hidden = !settings.kugel_kopf;  // … und nur mit gespeicherter Spiegelkugel
    $('kugelstat').textContent = settings.kugel_kopf
      ? `Gespeichert: Kopf ${settings.kugel_kopf}, Pan ${settings.kugel_pan}, Tilt ${settings.kugel_tilt}`
      : 'Noch keine Spiegelkugel gespeichert.';
    showSettings(); showHeads(); showLaser(s.laser);
  }).catch(() => {});
}
buildHeads();
buildLaser();
let startTab = 'show';
try { startTab = localStorage.getItem('tab') || 'show'; } catch (e) { /* Startseite */ }
const urlTab = new URLSearchParams(location.search).get('tab');   // z. B. ?tab=fein (Lesezeichen)
if (urlTab) startTab = urlTab;
if (new URLSearchParams(location.search).has('technik')) $('technik').open = true;
showTab($('tab-' + startTab) ? startTab : 'show');
loadState();
setInterval(loadState, 2000);                                                   // Einstellungen, Köpfe, Laser
// Status 5-mal pro Sekunde. Die Laufzeit der Abfrage (über HA-Ingress) wird gemessen: Der Schlag vom Gerät gilt
// für die Mitte der Abfrage, ab da zählt die Oberfläche selbst weiter (beatLoop)
setInterval(() => {
  const t0 = performance.now();
  api('api/status').then(d => { syncClock(d.sync, t0, performance.now()); showStatus(d); }).catch(() => {});
}, 200);
setInterval(beatLoop, 25);                     // Schlaganzeige 40-mal pro Sekunde (Zeitgeber: läuft auch, wo
                                                // der Browser keine Bildaufbau-Schleife anbietet)
