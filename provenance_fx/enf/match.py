"""Match an ENF trace against a reference: masked normalised cross-correlation (FFT),
sub-second peak refinement, an optional clock-drift search, and honest confidence numbers.

Short-clip guard: under ~2 minutes almost any reference has look-alike stretches
(Hua 2020; Grigoras), so the result is labelled unreliable no matter how high r is.
"""
from __future__ import annotations

import numpy as np
from scipy import signal, stats

from .extract import EnfTrace
from .reference import Reference

MIN_RELIABLE_S = 120.0
GOOD_S = 300.0


def _corr(a, b):
    """sum_i a[L+i] * b[i] for every L (a long, b short)."""
    return signal.fftconvolve(a, b[::-1], mode="valid")


def masked_ncc(r, q, min_overlap=0.8):
    """Pearson r between q and every same-length window of r, ignoring NaNs in either."""
    m = np.isfinite(r).astype(float)
    w = np.isfinite(q).astype(float)
    base = np.nanmedian(r)
    r0 = np.where(m > 0, r - base, 0.0)
    q0 = np.where(w > 0, q - np.nanmedian(q), 0.0)
    N = _corr(m, w)
    Sr = _corr(r0, w)
    Srr = _corr(r0 * r0, w)
    Sq = _corr(m, q0)
    Sqq = _corr(m, q0 * q0)
    Srq = _corr(r0, q0)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = Srq - Sr * Sq / N
        vr = Srr - Sr * Sr / N
        vq = Sqq - Sq * Sq / N
        ncc = cov / np.sqrt(vr * vq)
    ncc[(N < min_overlap * w.sum()) | ~np.isfinite(ncc) | (vr <= 1e-12)] = np.nan
    with np.errstate(invalid="ignore", divide="ignore"):
        # mean(recording) - mean(reference window), in Hz (removed by r, but informative)
        offset = (Sq / N + np.nanmedian(q)) - (Sr / N + base)
    return ncc, N, offset


def _smooth(f, n):
    if n <= 1:
        return f
    ok = np.isfinite(f)
    k = np.ones(int(n))
    num = np.convolve(np.where(ok, f, 0), k, "same")
    den = np.convolve(ok.astype(float), k, "same")
    out = num / np.maximum(den, 1e-9)
    out[den < 0.5 * n] = np.nan
    return out


def _acf_len(q):
    """Integrated autocorrelation length (samples) of the trace; used for effective sample size."""
    x = q[np.isfinite(q)]
    x = x - x.mean()
    if len(x) < 10 or x.std() == 0:
        return 1.0
    n = len(x)
    ac = np.correlate(x, x, "full")[n - 1:] / (x.var() * np.arange(n, 0, -1))
    s = 1.0
    for v in ac[1:min(n // 2, 2000)]:
        if v <= 0.05:
            break
        s += 2 * v
    return float(max(1.0, s))


def trace_on_grid(tr: EnfTrace):
    """1 s grid of the trace starting at tr.t[0]."""
    t = tr.t - tr.t[0]
    n = int(round(t[-1])) + 1
    tt = np.arange(n, dtype=float)
    ok = np.isfinite(tr.f)
    if ok.sum() < 2:
        return np.full(n, np.nan)
    q = np.interp(tt, t[ok], tr.f[ok])
    near = np.clip(np.searchsorted(t, tt), 0, len(t) - 1)
    q[~ok[near]] = np.nan
    return q


def match(tr: EnfTrace, ref: Reference, start=None, end=None, drift_ppm=100.0, top_k=5, log=None,
          level_tol_hz=0.010, use_level=None, smooth_s=None) -> dict:
    """Find where the recording's ENF best fits the reference.

    start/end: optional unix-second window for where the recording START may lie.
    level gate: Pearson r ignores the average frequency, but a recorder's clock is rarely
    off by more than ~200 ppm (10 mHz at 50 Hz), so for dated grid references lags whose
    mean frequency differs by more than level_tol_hz are penalised. Turn off (use_level=False)
    for sped-up/resampled media or relative references.
    smooth_s: force a common smoothing length (the grid race compares grids at one resolution).
    Returns a JSON-ready dict.
    """
    if use_level is None:
        use_level = not ref.relative
    log = log or (lambda m: None)
    q = trace_on_grid(tr)
    dur = float(len(q))
    ref1 = ref.to_1s()
    lo = None if start is None else start - 5
    hi = None if end is None else end + dur + tr.t[0] + 5
    rs = ref1.slice(lo, hi) if not ref1.relative or lo is not None else ref1
    r = rs.f.astype(np.float64)
    # make the reference look like the recording: same frame smoothing; 15 s data also smooths q
    r_s = _smooth(r, int(round(tr.frame_s)))
    q_s = q
    res_s = ref.resolution_s if smooth_s is None else max(float(smooth_s), ref.resolution_s)
    if res_s > 1.5:
        q_s = _smooth(q, int(round(res_s)))
        r_s = _smooth(r, int(round(res_s)))
    warnings = []
    if len(r_s) < len(q_s) + 2:
        raise ValueError("reference is shorter than the recording; widen the search window")
    if dur < MIN_RELIABLE_S:
        warnings.append(f"clip is only {dur:.0f} s: ENF matches under ~2 minutes are unreliable "
                        "(look-alike stretches are common)")
    elif dur < GOOD_S:
        warnings.append(f"clip is {dur:.0f} s: treat as low confidence (5+ minutes recommended)")
    if ref.resolution_s > 1.5:
        warnings.append(f"reference has {ref.resolution_s:.0f} s resolution (Elexon live feed); "
                        "timing is limited to roughly that")
    ncc_raw, N, offs = masked_ncc(r_s, q_s)
    if not np.isfinite(ncc_raw).any():
        raise ValueError("no overlap between recording and reference (gaps or too short)")
    ncc = ncc_raw.copy()
    if use_level:
        excess = np.clip(np.abs(offs) - level_tol_hz, 0, None)
        ncc = ncc_raw - excess / level_tol_hz      # 1 r-unit per extra tolerance width
    best = int(np.nanargmax(ncc))
    r1 = float(ncc[best])
    # sub-sample peak
    frac = 0.0
    if 0 < best < len(ncc) - 1 and np.isfinite(ncc[best - 1]) and np.isfinite(ncc[best + 1]):
        a, b, c = ncc[best - 1], ncc[best], ncc[best + 1]
        den = a - 2 * b + c
        frac = float(np.clip(0.5 * (a - c) / den, -0.5, 0.5)) if den < 0 else 0.0
    # drift search (only matters for long clips: 100 ppm over 1 h = 0.36 s)
    ppm_best = 0.0
    if dur > 1800 and drift_ppm > 0:
        tt = np.arange(len(q_s), dtype=float)
        okq = np.isfinite(q_s)
        lo_i, hi_i = max(0, best - 30), min(len(r_s), best + len(q_s) + 30)
        seg = r_s[lo_i:hi_i]
        for ppm in np.arange(-drift_ppm, drift_ppm + 1e-9, max(10.0, drift_ppm / 5)):
            qq = np.interp(tt * (1 + ppm * 1e-6), tt[okq], q_s[okq])
            n2, _, _ = masked_ncc(seg, qq)
            if np.isfinite(n2).any() and np.nanmax(n2) > r1 + 1e-4:
                r1 = float(np.nanmax(n2)); best = lo_i + int(np.nanargmax(n2)); ppm_best = float(ppm); frac = 0.0
    # runner-up outside an exclusion zone
    excl = int(max(60, 0.5 * dur))
    n2 = ncc.copy()
    n2[max(0, best - excl):best + excl + 1] = np.nan
    second = int(np.nanargmax(n2)) if np.isfinite(n2).any() else None
    r2 = float(n2[second]) if second is not None else float("nan")
    # candidates list (greedy peaks)
    cands = []
    n3 = ncc.copy()
    for _ in range(top_k):
        if not np.isfinite(n3).any():
            break
        i = int(np.nanargmax(n3))
        cands.append((i, float(n3[i])))
        n3[max(0, i - excl):i + excl + 1] = np.nan
    # statistics
    tau = _acf_len(q_s)
    n_valid = float(np.isfinite(q_s).sum())
    neff = max(4.0, n_valid / tau)
    z1 = np.arctanh(float(np.clip(r1, -0.999999, 0.999999))) * np.sqrt(neff - 3)
    p1 = float(stats.norm.sf(z1))
    n_trials = max(1.0, np.isfinite(ncc).sum() / max(tau, 1.0))
    p_false = float(min(1.0, p1 * n_trials))
    vals = ncc[np.isfinite(ncc)]
    mad = float(np.median(np.abs(vals - np.median(vals)))) * 1.4826 + 1e-9
    z_emp = float((r1 - np.median(vals)) / mad)
    gap = r1 - r2 if np.isfinite(r2) else r1
    # aligned overlay
    seg = r[best:best + len(q)]
    seg_s = r_s[best:best + len(q)]
    m = np.isfinite(seg_s) & np.isfinite(q_s[:len(seg_s)])
    offset = float(np.nanmean(q_s[:len(seg_s)][m] - seg_s[m])) if m.any() else float("nan")
    rmse = float(np.sqrt(np.nanmean((q_s[:len(seg_s)][m] - offset - seg_s[m]) ** 2))) if m.any() else float("nan")
    # recording start: reference index of q[0] corresponds to trace t[0]
    t_q0 = rs.time_of(best + frac)
    rec_start = t_q0 - float(tr.t[0])
    if use_level and np.isfinite(offset) and abs(offset) > 5 * level_tol_hz:
        warnings.append(f"the hum sits {offset * 1000:.0f} mHz away from the grid everywhere in the window: "
                        "it is probably not this grid's mains (or the media was sped up)")
    # label
    if dur < MIN_RELIABLE_S:
        label = "unreliable (too short)"
    elif r1 >= 0.85 and gap >= 0.15 and p_false < 1e-3 and dur >= GOOD_S:
        label = "strong"
    elif r1 >= 0.7 and gap >= 0.08 and p_false < 0.05:
        label = "moderate"
    elif r1 >= 0.5 and gap >= 0.05:
        label = "weak"
    else:
        label = "no match"
    if dur < GOOD_S and label == "strong":
        label = "moderate"
    thin_n = 1500
    idx = np.linspace(0, len(ncc) - 1, min(thin_n, len(ncc))).astype(int)
    # for the curve keep local maxima inside each bucket so peaks survive thinning
    if len(ncc) > thin_n:
        edges = np.linspace(0, len(ncc), thin_n + 1).astype(int)
        idx = np.array([a + int(np.nanargmax(ncc[a:b])) if np.isfinite(ncc[a:b]).any() else a
                        for a, b in zip(edges[:-1], edges[1:])])
    nn = lambda a: [None if not np.isfinite(v) else round(float(v), 5) for v in a]
    res = dict(
        reference=ref.info(), relative=ref.relative, duration_s=round(dur, 1),
        best_index=best, start_time=rec_start, start_label=ref.label_time(rec_start),
        ncc=round(max(r1, -1.0), 4), second_ncc=None if not np.isfinite(r2) else round(max(r2, -1.0), 4),
        second_start_label=None if second is None else ref.label_time(rs.time_of(second) - float(tr.t[0])),
        gap=round(gap, 4), p_false=p_false, n_trials=round(float(n_trials), 1), p_single=p1, z_empirical=round(z_emp, 2), effective_n=round(neff, 1),
        acf_len_s=round(tau, 1), rmse_mhz=round(rmse * 1000, 2), offset_mhz=round(offset * 1000, 2),
        drift_ppm=ppm_best, label=label, warnings=warnings, level_gate=bool(use_level),
        raw_ncc_at_best=None if not np.isfinite(ncc_raw[best]) else round(float(ncc_raw[best]), 4),
        candidates=[dict(start_label=ref.label_time(rs.time_of(i) - float(tr.t[0])), start_time=rs.time_of(i) - float(tr.t[0]),
                         ncc=round(v, 4)) for i, v in cands],
        overlay=dict(t=list(range(0, len(q), max(1, len(q) // 1200))),
                     rec=nn((q_s - (offset if np.isfinite(offset) else 0))[::max(1, len(q) // 1200)]),
                     ref=nn(seg_s[::max(1, len(q) // 1200)]) if len(seg_s) else [],
                     ref_raw=nn(seg[::max(1, len(q) // 1200)]) if len(seg) else []),
        curve=dict(t=[float(rs.time_of(i) - tr.t[0]) for i in idx], ncc=nn(np.clip(ncc[idx], -1, 1))),
    )
    log(f"best fit {res['start_label']}  r={r1:.3f}  runner-up r={r2:.3f}  p_false={p_false:.2g}  -> {label}")
    return res


def match_long(tr: EnfTrace, ref: Reference, start=None, end=None, chunk_s=20 * 86400, log=None, **kw) -> dict:
    """match() over a long reference (months) in overlapping chunks, so memory stays small.

    The best chunk's result is returned; its false-alarm probability is recomputed over ALL
    chunks (single-lag p times the total number of independent trials), and the runner-up is
    the best peak from any chunk outside the winner's exclusion zone.
    """
    log = log or (lambda m: None)
    ref1 = ref.to_1s()
    lo = ref1.t0 if start is None else max(ref1.t0, start)
    hi = ref1.t1 if end is None else min(ref1.t1, end)
    dur = float(tr.t[-1] - tr.t[0] + 1)
    if hi - lo <= chunk_s * 1.2:
        return match(tr, ref1, lo, hi, log=log, **kw)
    results = []
    a = lo
    while a < hi:
        b = min(hi, a + chunk_s)
        sub = ref1.slice(a - 5, b + dur + tr.t[0] + 10)
        if np.isfinite(sub.f).sum() > 1.5 * dur:
            try:
                results.append(match(tr, sub, a, b, log=lambda m: None, **kw))
            except ValueError:
                pass
        a = b
    if not results:
        raise ValueError("no overlap between recording and reference (gaps or too short)")
    results.sort(key=lambda m: -m["ncc"])
    best = dict(results[0])
    trials = sum(m["n_trials"] for m in results)
    best["p_false"] = float(min(1.0, best["p_single"] * trials))
    best["n_trials"] = round(float(trials), 1)
    excl = max(60, 0.5 * dur)
    others = [c for m in results for c in m["candidates"] if abs(c["start_time"] - best["start_time"]) > excl]
    if others:
        o = max(others, key=lambda c: c["ncc"])
        best["second_ncc"], best["second_start_label"] = o["ncc"], o["start_label"]
        best["gap"] = round(best["ncc"] - o["ncc"], 4)
        best["candidates"] = sorted(best["candidates"] + others, key=lambda c: -c["ncc"])[:5]
    best["chunks"] = len(results)
    r1, gap, pf = best["ncc"], best["gap"], best["p_false"]
    best["label"] = ("unreliable (too short)" if dur < MIN_RELIABLE_S else
                     "strong" if r1 >= 0.85 and gap >= 0.15 and pf < 1e-3 and dur >= GOOD_S else
                     "moderate" if r1 >= 0.7 and gap >= 0.08 and pf < 0.05 else
                     "weak" if r1 >= 0.5 and gap >= 0.05 else "no match")
    best["reference"] = ref.info()
    log(f"best fit over {len(results)} chunks: {best['start_label']} r={best['ncc']:.3f} "
        f"runner-up r={best['second_ncc']} p_false={best['p_false']:.2g}")
    return best


def continuity(tr: EnfTrace, ref: Reference, res: dict, seg_s=300.0, search_s=600.0) -> dict:
    """Match each seg_s window on its own near the global fit.

    If the windows agree with the global lag the ENF is continuous. Jumps mean missing
    audio (stream stalls) or edits; this is the classic ENF splice check (Grigoras 2005).
    """
    q = trace_on_grid(tr)
    ref1 = ref.to_1s()
    out = []
    n = int(seg_s)
    t_start = res["start_time"] + float(tr.t[0])
    for i0 in range(0, len(q) - n + 1, n):
        sub = q[i0:i0 + n]
        if np.isfinite(sub).mean() < 0.6:
            out.append(dict(t=i0, shift_s=None, ncc=None))
            continue
        a = t_start + i0 - search_s
        b = t_start + i0 + n + search_s
        rs = ref1.slice(a, b)
        r = _smooth(rs.f, int(round(tr.frame_s)))
        qq = sub
        if ref.resolution_s > 1.5:
            r = _smooth(rs.f, int(round(ref.resolution_s)))
            qq = _smooth(sub, int(round(ref.resolution_s)))
        if len(r) <= len(qq):
            out.append(dict(t=i0, shift_s=None, ncc=None))
            continue
        ncc, _, offs = masked_ncc(r, qq)
        if not np.isfinite(ncc).any():
            out.append(dict(t=i0, shift_s=None, ncc=None))
            continue
        if not ref.relative:
            ncc = ncc - np.clip(np.abs(offs) - 0.010, 0, None) / 0.010
        j = int(np.nanargmax(ncc))
        shift = rs.time_of(j) - (t_start + i0)
        out.append(dict(t=i0, shift_s=round(float(shift), 1), ncc=round(float(ncc[j]), 3)))
    shifts = [o["shift_s"] for o in out if o["shift_s"] is not None and o["ncc"] is not None and o["ncc"] > 0.5]
    tol = max(5.0, 1.5 * ref.resolution_s)
    jumps = int(sum(abs(b - a) > tol for a, b in zip(shifts, shifts[1:])))
    verdict = ("continuous" if shifts and jumps == 0 and max(abs(s) for s in shifts) <= tol else
               "possible gaps or edits" if shifts else "not enough clean ENF to check")
    return dict(segments=out, jumps=jumps, verdict=verdict, segment_s=seg_s)


def apply_continuity(m: dict, c: dict, min_ncc=0.8) -> dict:
    """If the continuity check found a timeline break (stall, cut), the global fit sits on the longest
    stretch, so its start is off by the missing seconds. Report the start of the first clean segment as
    well and flag the break; the global start_time is left unchanged."""
    if not m or not c or c.get("jumps", 0) == 0:
        return m
    segs = [s for s in c.get("segments", []) if s.get("shift_s") is not None and (s.get("ncc") or 0) >= min_ncc]
    if not segs or segs[0]["t"] != 0:
        return m
    m["timeline_break"] = True
    m["start_time_first_segment"] = float(m["start_time"]) + float(segs[0]["shift_s"])
    import datetime as _dt
    lab = _dt.datetime.fromtimestamp(m["start_time_first_segment"], _dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    m.setdefault("warnings", []).append(
        f"timeline break: audio seems to be missing inside the clip; the first part lines up with a start of {lab} "
        f"({segs[0]['shift_s']:+.1f} s from the best overall fit). Trust the start to tens of seconds, not to the second.")
    return m
