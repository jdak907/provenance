"""Grid-of-origin heuristic from ENF statistics (after Hajj-Ahmad et al. 2015, SP Cup 2016).

Step 1: nominal 50 vs 60 Hz from the hum itself (reliable when hum is present).
Step 2: within that family, compare drift statistics (spread, step sizes, Haar wavelet
variances at 8-256 s, AR(2) of the 8 s series) with profiles learned from public
power-grid logs. A linear discriminant (trained with scikit-learn, stored as plain JSON)
gives class probabilities.

This is a HEURISTIC: profiles come from one or a few logging sites per grid, from
particular weeks or months, and recorded ENF is noisier than mains logs. Treat
anything under ~70 % as "can't tell".
"""
from __future__ import annotations

import json
import os

import numpy as np

PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "legacy_grid_profiles_v1.json")
FEATURES = ["log_std", "log_d1", "log_d8", "log_d30", "log_w8", "log_w16", "log_w32", "log_w64",
            "log_w128", "ar1", "ar2"]


def _smooth(f, n):
    if n <= 1:
        return f
    k = np.ones(int(n)) / n
    return np.convolve(f, k, "valid")


def features(f, nominal, frame_s=8.0):
    """f: 1 s ENF series (Hz), NaNs allowed (linearly bridged). Returns feature vector or None."""
    f = np.asarray(f, float)
    ok = np.isfinite(f)
    if ok.sum() < 120:
        return None
    idx = np.arange(len(f))
    f = np.interp(idx, idx[ok], f[ok])
    f = _smooth(f, int(round(frame_s)))
    d = (f - nominal) * 1000.0          # mHz
    lg = lambda v: float(np.log10(max(v, 1e-4)))
    feat = dict(
        log_std=lg(np.std(d)),
        log_d1=lg(np.std(np.diff(d))),
        log_d8=lg(np.std(d[8:] - d[:-8])) if len(d) > 16 else 0.0,
        log_d30=lg(np.std(d[30:] - d[:-30])) if len(d) > 60 else 0.0,
    )
    for s in (8, 16, 32, 64, 128):
        n = (len(d) // (2 * s)) * 2 * s
        if n < 4 * s:
            feat[f"log_w{s}"] = feat.get(f"log_w{s // 2}", 0.0)
            continue
        blk = d[:n].reshape(-1, 2, s).mean(axis=2)
        feat[f"log_w{s}"] = lg(np.std(blk[:, 0] - blk[:, 1]) / np.sqrt(2))
    y = d[::8]
    y = y - y.mean()
    if len(y) > 10 and np.std(y) > 0:
        X = np.stack([y[1:-1], y[:-2]], 1)
        coef, *_ = np.linalg.lstsq(X, y[2:], rcond=None)
        feat["ar1"], feat["ar2"] = float(coef[0]), float(coef[1])
    else:
        feat["ar1"], feat["ar2"] = 0.0, 0.0
    return np.array([feat[k] for k in FEATURES])


def load_profiles(path=PROFILE_PATH):
    if not os.path.exists(path):
        return None
    return json.load(open(path))


def classify(trace, nominal=None, profiles=None) -> dict:
    """trace: EnfTrace. Returns nominal family, per-grid probabilities and an honest verdict."""
    from provenance_fx.enf.match import trace_on_grid

    nominal = nominal or trace.nominal
    family = "50 Hz grids (Europe, UK, most of Asia/Africa/Australia, parts of Japan)" if nominal == 50 else \
        "60 Hz grids (North America, parts of South America, Korea, Taiwan, west Japan, Philippines, Saudi Arabia)"
    out = dict(nominal=nominal, family=family, probs={}, best=None, verdict="", note="")
    prof = profiles or load_profiles()
    q = trace_on_grid(trace)
    fv = features(q, nominal, trace.frame_s)
    if prof is None or fv is None:
        out["verdict"] = f"{nominal} Hz family only" + (" (too short for grid statistics)" if fv is None else "")
        return out
    model = prof.get(str(nominal))
    if not model:
        out["verdict"] = f"{nominal} Hz family only (no profiles for this family)"
        return out
    z = (fv - np.array(model["mean"])) / np.array(model["scale"])
    logits = np.array(model["coef"]) @ z + np.array(model["intercept"])
    if len(model["classes"]) == 2 and len(logits) == 1:
        logits = np.array([0.0, logits[0]])
    p = np.exp(logits - logits.max())
    p /= p.sum()
    probs = {c: float(v) for c, v in zip(model["classes"], p)}
    best = max(probs, key=probs.get)
    out.update(probs=probs, best=best, features=dict(zip(FEATURES, [round(float(v), 3) for v in fv])),
               trained_on=model.get("trained_on"), cv_accuracy=model.get("cv_accuracy"))
    if trace.duration < 300:
        out["verdict"] = f"{nominal} Hz family; clip too short for a grid guess (best guess {best}, {probs[best]:.0%})"
    elif probs[best] >= 0.7:
        out["verdict"] = (f"{nominal} Hz family; statistics look most like {best} ({probs[best]:.0%}) - "
                          "EXPERIMENTAL hint only, often wrong on real recordings")
    else:
        out["verdict"] = f"{nominal} Hz family; statistics inconclusive (best {best}, {probs[best]:.0%})"
    out["note"] = ("Experimental. Validation: about 45% right on ENF-WHU recordings (4 classes) and 1 of 7 on "
                   "UK stream captures, which it tends to call 'Nordic'. Only the 50/60 Hz family is reliable.")
    return out
