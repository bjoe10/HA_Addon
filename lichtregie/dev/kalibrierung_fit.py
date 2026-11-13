#!/usr/bin/env python3
"""Kalibrier-Fit für die beiden Moving Heads (nur Standardbibliothek).

Raumkoordinaten in Metern:
  x = 0 linke Wand, x = 5 rechte Wand (vom TV aus gesehen)
  y = 0 TV-Wand,    y = 6 Kopf-Wand
  z = 0 Boden,      z = 2.5 Decke

Pro Kopf wird ein Modell gefittet:
  Richtung von Kopf P zum Ziel T:  phi = atan2(dx, dy)  (Pan-Winkel, Grad)
                                   theta = atan2(dz, horiz) (Neigung, Grad)
  DMX pan  = ap + bp * phi
  DMX tilt = at + bt * theta
Freie Parameter: P (3), ap, bp, at, bt. bp und bt dürfen negativ sein.

Die Messpunkte stehen unten. Die Zielkoordinaten sind Schätzungen aus den Angaben des Nutzers.
Aufruf: python3 kalibrierung_fit.py
"""
import math

# Messpunkte: Ziel (x, y, z) in m, gemessene DMX-Werte (16 Bit) aus HA
TARGETS = {
    "1 TV-Mitte": (2.5, 0.0, 1.0),
    "2 rechte Ecke oben TV-Wand": (4.9, 0.0, 2.4),
    "3 linke Ecke oben TV-Wand": (0.1, 0.0, 2.4),
    "4 kleiner Tisch": (2.2, 3.5, 0.75),
    "5 rechts neben TV": (3.8, 0.0, 1.0),
}
HEADS = {
    "Kopf 1": {
        "pan": [41216, 43776, 39168, 38400, 42496],
        "tilt": [7168, 3840, 2560, 15104, 7168],
    },
    "Kopf 2": {
        "pan": [24832, 26880, 22272, 27392, 26112],
        "tilt": [58112, 61952, 62720, 50176, 58112],
    },
}
PAN_MAX_DEG = 540.0   # nur für die Ausgabe in Grad, nicht für den Fit


def angles(p, t):
    dx, dy, dz = t[0] - p[0], t[1] - p[1], t[2] - p[2]
    phi = math.degrees(math.atan2(dx, dy))
    theta = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    return phi, theta


def predict(params, target):
    px, py, pz, ap, bp, at, bt = params
    phi, theta = angles((px, py, pz), target)
    return ap + bp * phi, at + bt * theta


def cost(params, pan, tilt, targets):
    total = 0.0
    for (name, t), mp, mt in zip(targets, pan, tilt):
        pp, pt = predict(params, t)
        total += (mp - pp) ** 2 + (mt - pt) ** 2
    return total


def nelder_mead(f, x0, steps, iters=8000):
    n = len(x0)
    pts = [list(x0)]
    for i in range(n):
        p = list(x0)
        p[i] += steps[i]
        pts.append(p)
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        pts = [pts[i] for i in order]
        vals = [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) < 1e-9:
            break
        cen = [sum(p[j] for p in pts[:-1]) / n for j in range(n)]
        xr = [cen[j] + (cen[j] - pts[-1][j]) for j in range(n)]
        fr = f(xr)
        if fr < vals[0]:
            xe = [cen[j] + 2 * (cen[j] - pts[-1][j]) for j in range(n)]
            fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            if fr < vals[-1]:
                xc = [cen[j] + 0.5 * (xr[j] - cen[j]) for j in range(n)]
            else:
                xc = [cen[j] + 0.5 * (pts[-1][j] - cen[j]) for j in range(n)]
            fc = f(xc)
            if fc < min(fr, vals[-1]):
                pts[-1], vals[-1] = xc, fc
            else:
                for i in range(1, n + 1):
                    pts[i] = [pts[0][j] + 0.5 * (pts[i][j] - pts[0][j]) for j in range(n)]
                    vals[i] = f(pts[i])
    best = min(range(n + 1), key=lambda i: vals[i])
    return pts[best], vals[best]


WALL_Y = 5.9   # Abstand der Köpfe zur Wand bei y = 6 (Schätzung)
MOUNT_Z = 2.5  # Montagehöhe, gemessen


def fit_head(pan, tilt, targets):
    """Fit mit bekannter Höhe und Wandnähe; frei bleiben x-Position und die vier Achsparameter."""
    best = None
    for x_start in (0.1, 2.5, 4.9):
        for sp in (+1, -1):
            for st in (+1, -1):
                bp0, bt0 = sp * 121.0, st * 285.0
                pos0 = (x_start, WALL_Y, MOUNT_Z)
                phis = [angles(pos0, t) for _, t in targets]
                ap0 = sum(m - bp0 * ph for m, (ph, _) in zip(pan, phis)) / len(pan)
                at0 = sum(m - bt0 * th for m, (_, th) in zip(tilt, phis)) / len(tilt)
                x0 = [x_start, ap0, bp0, at0, bt0]
                steps = [0.5, 500.0, 30.0, 500.0, 30.0]

                def full(q):
                    return [q[0], WALL_Y, MOUNT_Z, q[1], q[2], q[3], q[4]]

                q, val = nelder_mead(lambda q: cost(full(q), pan, tilt, targets), x0, steps)
                if best is None or val < best[1]:
                    best = (full(q), val)
    return best


def report(name, params, val, pan, tilt, targets):
    px, py, pz, ap, bp, at, bt = params
    rms = math.sqrt(val / (2 * len(targets)))
    print(f"\n{name}")
    print(f"  Position: x={px:.2f} m, y={py:.2f} m, z={pz:.2f} m")
    print(f"  Pan:  DMX = {ap:.0f} + {bp:.1f} * phi   (1 Grad = {abs(bp):.0f} DMX)")
    print(f"  Tilt: DMX = {at:.0f} + {bt:.1f} * theta   (1 Grad = {abs(bt):.0f} DMX)")
    print(f"  RMS-Fehler: {rms:.0f} DMX, Pan ca. {rms / abs(bp):.2f} Grad, Tilt ca. {rms / abs(bt):.2f} Grad")
    print("  Punkt                       Pan gem / mod    Tilt gem / mod   Abweichung Pan/Tilt (DMX)")
    for (label, t), mp, mt in zip(targets, pan, tilt):
        pp, pt = predict(params, t)
        print(f"  {label:<28}{mp:>7} / {pp:>7.0f}   {mt:>6} / {pt:>7.0f}   {mp - pp:>+6.0f} / {mt - pt:>+6.0f}")


def main():
    targets = list(TARGETS.items())
    for name, data in HEADS.items():
        params, val = fit_head(data["pan"], data["tilt"], targets)
        report(name, params, val, data["pan"], data["tilt"], targets)


if __name__ == "__main__":
    main()
