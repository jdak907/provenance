"""Measure one flyover from the spectrogram: speed, closest slant distance, CPA time, base pitch.

Fits the ideal straight-line Doppler curve to the traced ridge. Real aircraft
turn and change speed, so the fit is imperfect; we therefore report generous
ranges, as the video does, and leave the exact geometry to the later scoring step.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import least_squares

from .physics import C_DEFAULT, straight_line_curve
from .spectro import Spectrogram, trace_ridge


@dataclass
class EventMeasurement:
    name: str
    t_start: float          # audio seconds
    t_end: float
    f0: float               # base (rest-frame) pitch, Hz
    speed: float            # m/s
    slant_cpa: float        # m
    t_cpa: float            # audio seconds when closest point is heard
    speed_range: tuple
    slant_range: tuple
    f0_rel_tol: float       # sweep +/- this fraction of f0 during scoring
    t_tol: float            # sweep +/- seconds during scoring
    rms_hz: float           # robust fit residual (1.4826 x median absolute error), Hz
    fmin: float = 30.0
    fmax: float = 400.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["speed_range"] = tuple(d["speed_range"])
        d["slant_range"] = tuple(d["slant_range"])
        return cls(**d)


def _initial_guess(t, f, c):
    f_hi, f_lo = np.percentile(f, 92), np.percentile(f, 8)
    f0 = 2 * f_hi * f_lo / (f_hi + f_lo)
    v = c * (f_hi - f_lo) / (f_hi + f_lo)
    i = int(np.argmin(np.abs(f - f0)))
    return f0, v, t[i]


def fit_event(spec: Spectrogram, t0: float, t1: float, name: str = "event", fmin=None, fmax=None,
              c: float = C_DEFAULT, min_bright: float = 1.5, ridge=None) -> EventMeasurement:
    if ridge is None:
        times, freqs, strength = trace_ridge(spec, t0, t1, fmin, fmax)
    else:
        times, freqs, strength = ridge
    good = strength >= min_bright
    if good.sum() < 20:
        good = strength >= np.percentile(strength, 50)
    tt, ff, ww = times[good], freqs[good], np.sqrt(strength[good])
    f0, v, tc = _initial_guess(tt, ff, c)

    def resid(p):
        return ww * (straight_line_curve(tt, p[0], p[1], p[2], p[3], c) - ff)

    best = None
    for d0 in (150, 300, 600, 1000, 1600, 2500, 4000, 6000):
        r = least_squares(resid, [f0, v, d0, tc],
                          bounds=([10, 5, 30, tt[0] - 60], [2000, 300, 15000, tt[-1] + 60]),
                          loss="soft_l1", f_scale=1.0)
        if best is None or r.cost < best.cost:
            best = r
    f0, v, d, tc = best.x
    res = straight_line_curve(tt, f0, v, d, tc, c) - ff
    rms = float(1.4826 * np.median(np.abs(res)))  # robust spread: ignores stray noise frames
    try:
        J = best.jac
        cov = np.linalg.pinv(J.T @ J) * (2 * best.cost / max(1, len(tt) - 4))
        sig = np.sqrt(np.clip(np.diag(cov), 0, None))
    except Exception:
        sig = np.zeros(4)
    # Generous ranges: real flight paths are not straight lines.
    # Speed range is lopsided on purpose: turns and climbs bend the line of sight, which
    # lowers the radial speed the curve shows, so a fit tends to UNDER-read true speed.
    dv_lo = max(3 * sig[1], 0.2 * v, 10.0)
    dv_hi = max(3 * sig[1], 0.4 * v, 15.0)
    dd_lo = max(3 * sig[2], 0.45 * d)
    dd_hi = max(3 * sig[2], 0.8 * d)
    return EventMeasurement(
        name=name, t_start=float(t0), t_end=float(t1), f0=float(f0), speed=float(v),
        slant_cpa=float(d), t_cpa=float(tc),
        speed_range=(float(max(5.0, v - dv_lo)), float(v + dv_hi)),
        slant_range=(float(max(30.0, d - dd_lo)), float(d + dd_hi)),
        f0_rel_tol=float(max(0.03, 3 * sig[0] / f0)), t_tol=float(max(5.0, 3 * sig[3])),
        rms_hz=rms, fmin=float(fmin or spec.f[0]), fmax=float(fmax or spec.f[-1]),
    )
