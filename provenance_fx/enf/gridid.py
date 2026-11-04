"""Fallback grid guess from ENF statistics, for when the recording time is NOT known.

(If the time is roughly known, use the grid race in race.py: it is far more decisive.)

Step 1: nominal 50 vs 60 Hz from the hum itself (reliable when hum is present).
Step 2: within that family, a calibrated multinomial logistic model on drift statistics:
multi-scale increment spread (1-128 s), Haar wavelet variances, spectral shape of the
fluctuations, autocorrelation, step/ramp statistics and the mean offset from nominal.

Root-cause fix (v2): v1 was trained on clean grid logs, but a microphone recording's ENF
has extractor smoothing, estimation noise and gaps. Its fine-scale statistics looked
nothing like any grid log, and the nearest match was usually the calmest one, Nordic.
v2 is trained on ENF EXTRACTED from simulated recordings of real grid logs
(simulate.mic_chain -> extract_enf), cross-validated by day, temperature-calibrated,
and it says "unknown" when the top probability is below a threshold chosen on
held-out days.
"""
from __future__ import annotations

import json
import os

import numpy as np
from scipy import signal, stats

PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grid_profiles.json")
LAGS = (1, 2, 4, 8, 16, 32, 64, 128)
FEATURES = ([f"log_d{l}" for l in LAGS] + ["log_std", "log_absmean"] +
            [f"log_w{s}" for s in (8, 16, 32, 64, 128)] +
            [f"psd_b{i}" for i in range(5)] + ["psd_slope"] +
            ["acf10", "acf30", "acf60", "acf120"] +
            ["kurt_d1", "kurt_d8", "kurt_d32", "jump_frac", "ramp_frac"])
NAMES = {"GB": "Great Britain", "CE": "Continental Europe", "NORDIC": "Nordic", "CHINA": "China (WHU logs)",
         "US-WEST": "US West", "US-TEXAS": "US Texas", "US-EAST": "US East"}


def _bridge(f):
    f = np.asarray(f, float)
    ok = np.isfinite(f)
    if ok.sum() < 120:
        return None
    idx = np.arange(len(f))
    return np.interp(idx, idx[ok], f[ok]), ok.mean()


def features(f, nominal):
    """f: 1 s ENF series (Hz) as extracted from a recording. Returns a vector or None."""
    b = _bridge(f)
    if b is None:
        return None
    f, _ = b
    d = (f - nominal) * 1000.0  # mHz
    lg = lambda v: float(np.log10(max(float(v), 1e-4)))
    fe = {}
    for l in LAGS:
        fe[f"log_d{l}"] = lg(np.std(d[l:] - d[:-l])) if len(d) > 4 * l else lg(np.std(np.diff(d))) + np.log10(l) / 2
    fe["log_std"] = lg(np.std(d))
    fe["log_absmean"] = lg(abs(np.mean(d)) + 2.0)
    for s in (8, 16, 32, 64, 128):
        n = (len(d) // (2 * s)) * 2 * s
        if n < 4 * s:
            fe[f"log_w{s}"] = fe.get(f"log_w{s // 2}", fe["log_std"])
            continue
        blk = d[:n].reshape(-1, 2, s).mean(axis=2)
        fe[f"log_w{s}"] = lg(np.std(blk[:, 0] - blk[:, 1]) / np.sqrt(2))
    x = signal.detrend(d)
    fr, p = signal.welch(x, fs=1.0, nperseg=min(256, len(x)))
    edges = [1 / 256, 1 / 128, 1 / 64, 1 / 32, 1 / 16, 1 / 8]
    tot = p[(fr >= edges[0]) & (fr < edges[-1])].sum() + 1e-12
    for i in range(5):
        m = (fr >= edges[i]) & (fr < edges[i + 1])
        fe[f"psd_b{i}"] = float(np.log10(p[m].sum() / tot + 1e-6)) if m.any() else -6.0
    m = (fr >= 1 / 128) & (fr <= 1 / 10) & (p > 0)
    fe["psd_slope"] = float(np.polyfit(np.log10(fr[m]), np.log10(p[m]), 1)[0]) if m.sum() > 3 else -2.0
    xc = d - d.mean()
    v = np.dot(xc, xc) + 1e-12
    for l in (10, 30, 60, 120):
        fe[f"acf{l}"] = float(np.dot(xc[l:], xc[:-l]) / v) if len(xc) > 2 * l else 0.0
    for l in (1, 8, 32):
        dd = d[l:] - d[:-l]
        fe[f"kurt_d{l}"] = float(np.clip(stats.kurtosis(dd), -2, 20)) if len(dd) > 20 else 0.0
    d8 = d[8:] - d[:-8]
    mad = np.median(np.abs(d8 - np.median(d8))) * 1.4826 + 1e-6
    fe["jump_frac"] = float(np.mean(np.abs(d8) > 4 * mad))
    d60 = d[60:] - d[:-60] if len(d) > 120 else d8
    fe["ramp_frac"] = float(np.mean(np.abs(d60) > 2 * (np.std(d) + 1e-6)))
    return np.array([fe[k] for k in FEATURES])


def load_profiles(path=PROFILE_PATH):
    if not os.path.exists(path):
        return None
    return json.load(open(path))


def predict_proba(model, fv):
    z = (fv - np.array(model["mean"])) / np.array(model["scale"])
    logits = (np.array(model["coef"]) @ z + np.array(model["intercept"])) / model.get("temperature", 1.0)
    p = np.exp(logits - logits.max())
    return p / p.sum()


def classify(trace, nominal=None, profiles=None, det=None) -> dict:
    """trace: EnfTrace. Returns nominal family, calibrated per-grid probabilities, and a verdict that
    abstains ("unknown") when the evidence is weak."""
    from .match import trace_on_grid

    nominal = nominal or trace.nominal
    family = "50 Hz grids (Europe, UK, most of Asia/Africa/Australia, parts of Japan)" if nominal == 50 else \
        "60 Hz grids (North America, parts of South America, Korea, Taiwan, west Japan, Philippines, Saudi Arabia)"
    out = dict(nominal=nominal, family=family, probs={}, best=None, decision="unknown", verdict="", note="",
               method="statistics (time unknown)")
    prof = profiles or load_profiles()
    q = trace_on_grid(trace)
    fv = features(q, nominal)
    model = (prof or {}).get(str(nominal))
    if fv is None or not model:
        out["verdict"] = f"{nominal} Hz family only" + (" (too little ENF for grid statistics)" if fv is None else "")
        return out
    p = predict_proba(model, fv)
    probs = {c: float(v) for c, v in zip(model["classes"], p)}
    best = max(probs, key=probs.get)
    thr = model.get("abstain_below", 0.7)
    valid = float(np.isfinite(q).mean())
    out.update(probs=probs, best=best, threshold=thr, cv=model.get("cv"),
               trained_on=model.get("trained_on"), features=dict(zip(FEATURES, [round(float(v), 3) for v in fv])))
    reasons = []
    if trace.duration < model.get("min_duration_s", 300):
        reasons.append(f"clip shorter than {model.get('min_duration_s', 300):.0f} s")
    if valid < 0.6:
        reasons.append("ENF trace has too many gaps")
    if det is not None and det.get("verdict") == "absent":
        reasons.append("no usable mains hum")
    # out-of-distribution gate: traces much noisier than anything in training (heavily compressed
    # streams, weak hum) make every statistic unreliable; v2 without this gate called such clips
    # "GB" partly BECAUSE they were noisy (GB is the most variable class).
    ood = model.get("ood_max") or {}
    fd = dict(zip(FEATURES, fv))
    noisy = [k for k, lim in ood.items() if k in fd and fd[k] > lim]
    if noisy:
        reasons.append("ENF trace is noisier than any training data (" + ", ".join(noisy) + ")")
        out["out_of_distribution"] = noisy
    if probs[best] < thr:
        reasons.append(f"top probability {probs[best]:.0%} is under the {thr:.0%} abstain threshold")
    if reasons:
        out["verdict"] = f"{nominal} Hz family; grid UNKNOWN ({'; '.join(reasons)}). Best guess {NAMES.get(best, best)} {probs[best]:.0%}."
    else:
        out["decision"] = best
        out["verdict"] = (f"{nominal} Hz family; statistics point to {NAMES.get(best, best)} ({probs[best]:.0%}). "
                          "Statistical hint, not proof: give a time window to run the grid race.")
    cv = model.get("cv") or {}
    out["note"] = ("Calibrated on held-out days of simulated recordings: "
                   f"{cv.get('answered_accuracy', 0):.0%} right when it answers, abstains {cv.get('abstain_rate', 0):.0%}. "
                   "Covers only grids with free training logs: " + ", ".join(NAMES.get(c, c) for c in model["classes"]) + ".")
    return out
