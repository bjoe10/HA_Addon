#!/usr/bin/env python3
"""Wertet eine Aufnahme vom Gerät aus: Was ging wirklich an die Köpfe, und warum standen sie?

- Lücken: Abstände zwischen Show-Bildern und zwischen Art-Net-Sendungen über 50 ms (technisches Ruckeln).
- Stillstand: Zeiten, in denen sich ein Kopf länger als STILL Sekunden nicht bewegt hat, mit Szene und Teil.
- Markierungen „Hängt jetzt“: für jede, was in den 3 s davor passiert ist (Lücken, Stillstand, Szene, Ereignisse
  der Schlagzählung wie Takt-Anker oder Tempo-Wechsel).
Zeiten in Sekunden ab Beginn der Aufnahme.
Aufruf: python3 dev/show_auswerten.py aufnahme.zip [weitere.zip …]
"""
import json
import sys
import zipfile
from pathlib import Path

STILL = 0.75        # so lange ohne Bewegung gilt als Stillstand
MOVE = 30           # kleinere Änderung von Pan/Tilt (16 Bit) zählt nicht als Bewegung (ca. 0,3°)
LOOK = 3.0          # so weit vor einer Markierung „Hängt jetzt“ wird geschaut


def gaps(times, limit=0.05):
    return [(a, b - a) for a, b in zip(times, times[1:]) if b - a > limit]


def still_spans(trace, k):
    """[(von, bis, Szene)] in denen sich Kopf k nicht bewegt hat."""
    spans, start, last = [], None, None
    for r in trace:
        head = (r.get("koepfe") or {}).get(str(k))
        if head is None:
            continue
        if last is not None and abs(head[0] - last[0]) <= MOVE and abs(head[1] - last[1]) <= MOVE:
            start = start if start is not None else prev_t
        else:
            if start is not None and prev_t - start >= STILL:
                spans.append((start, prev_t, prev_info))
            start = None
        last, prev_t, prev_info = head, r["t"], (r.get("info") or "")
    if start is not None and last is not None and prev_t - start >= STILL:
        spans.append((start, prev_t, prev_info))
    return spans


def main(path):
    data = json.loads(zipfile.ZipFile(path).read("daten.json"))
    t0 = data["start"]
    trace = [r for r in data["trace"] if r.get("koepfe")]
    rel = lambda t: t - t0  # noqa: E731
    print(f"\n== {Path(path).name}: {data['meta'].get('titel')} · {len(trace)} Bilder mit Kopf-Werten, "
          f"{len(data.get('sends', []))} Sendungen, {len(data.get('haenger', []))} × „Hängt jetzt“")
    if not trace:
        print("   keine Kopf-Werte (Aufnahme mit älterer Version?)")
        return
    dur = trace[-1]["t"] - trace[0]["t"]
    fg = gaps([r["t"] for r in trace])
    sg = gaps(data.get("sends", []))
    print(f"   Show-Bilder: {len(trace) / max(dur, 1e-6):.1f}/s, Lücken > 50 ms: {len(fg)}"
          + (f" (größte {max(g for _, g in fg) * 1000:.0f} ms bei {rel(max(fg, key=lambda x: x[1])[0]):.1f} s)" if fg else ""))
    if data.get("sends"):
        print(f"   Sendungen: Lücken > 50 ms: {len(sg)}"
              + (f" (größte {max(g for _, g in sg) * 1000:.0f} ms bei {rel(max(sg, key=lambda x: x[1])[0]):.1f} s)" if sg else ""))
    for k in (1, 2):
        spans = still_spans(trace, k)
        total = sum(b - a for a, b, _ in spans)
        print(f"   Kopf {k}: {len(spans)}× Stillstand über {STILL} s, zusammen {total:.1f} s von {dur:.0f} s")
        for a, b, info in spans[:12]:
            print(f"      {rel(a):6.1f}–{rel(b):6.1f} s ({b - a:.1f} s): {info[:70]}")
    for m in data.get("haenger", []):
        win = [r for r in trace if m - LOOK <= r["t"] <= m]
        print(f"   „Hängt jetzt“ bei {rel(m):.1f} s:")
        if not win:
            print("      keine Bilder davor")
            continue
        wf = [g for g in fg if m - LOOK <= g[0] <= m]
        ws = [g for g in sg if m - LOOK <= g[0] <= m]
        print(f"      Lücken davor: Bilder {[round(g * 1000) for _, g in wf]} ms, Sendungen {[round(g * 1000) for _, g in ws]} ms")
        for k in (1, 2):
            sp = [s for s in still_spans(win, k)]
            print(f"      Kopf {k}: " + (", ".join(f"steht {rel(a):.1f}–{rel(b):.1f} s" for a, b, _ in sp) or "bewegt sich"))
        infos = []
        for r in win:
            i = (r.get("info") or "")[:60]
            if not infos or infos[-1] != i:
                infos.append(i)
        print(f"      Szene: {' → '.join(infos)}")
        ev = sorted({e for r in win for e in r.get("ereignisse", [])})
        if ev:
            print(f"      Ereignisse der Zählung: {ev}")
        b = [r["b"] for r in win if r.get("b") is not None]
        if len(b) > 2:
            jumps = [round(y - x, 2) for x, y in zip(b, b[1:]) if abs(y - x) > 0.3]
            print(f"      Schlagnummer {b[0]:.1f} → {b[-1]:.1f}" + (f", Sprünge {jumps}" if jumps else ""))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
