"""Light-flicker ENF from the PICTURE of a video (phase 2 of the ENF tab).

Mains-powered lights flicker at twice the mains frequency (100 Hz on 50 Hz grids, 120 Hz on 60 Hz grids).
A camera picks that up in two ways:

1. Rolling shutter (most phones and webcams). The sensor reads one row after another, so within one
   frame each row is a sample at a slightly later time. The flicker shows up as faint horizontal bands.
   Per frame we fit a sinusoid across the rows; its phase is the flicker phase at the frame's start.
   Demodulating that phase from frame to frame gives the flicker frequency, so the grid frequency.
   This works at any frame rate, including exactly 30 or 25 fps, as long as the read-out time (the time
   to read all rows) is known. When it is not given, it is searched from the band spacing.
   (Su et al. ICIP 2014; Choi et al. TIFS 2023; Han et al. SPL 2022; read-out estimation as in
   Hajj-Ahmad et al. SPL 2016.)
2. Frame mean (global shutter, or as a second opinion). The average brightness per frame is sampled at
   the frame rate, so the flicker aliases to a low frequency: 120 Hz at 29.97 fps lands at about 0.12 Hz.
   We track that aliased line. It fails when the alias sits at 0 Hz (exactly 30 or 60 fps on a 60 Hz grid,
   exactly 25 or 50 fps on a 50 Hz grid). (Garg et al. TIFS 2013.)

Before either path: only bright, unclipped, static parts of the picture are used; frames with camera motion
or sudden exposure changes are dropped, and the static scene is divided out with a slow running mean.
A presence check (the same ENF detector as audio, plus a band-contrast test) abstains when there is no flicker.

Assumptions [VERIFY on real cameras]: rows are read top to bottom in the stored (not auto-rotated) frame;
the frame rate is constant (variable-frame-rate phone files are treated as constant).
"""
from __future__ import annotations

import json
import subprocess
from fractions import Fraction

import numpy as np

from .extract import EnfTrace, despike

ROWS = 240              # decoded rows (row-averaged with area scaling): the time samples of a rolling shutter
COLS = 16               # decoded column blocks: used for region selection
BG_CHUNK_S = 60.0       # static-scene background: chunk means, linearly interpolated in time
MIN_CLIP_S = 30        # shorter clips: 'too short'
MIN_SEG_S = 4.0         # shortest usable stretch between motion / exposure events
WIN_RS = 12.0           # tracking window, rolling-shutter path (s); long enough to average codec keyframe pumping
WIN_FM_SLOW = 32.0      # tracking window, frame-mean path when the alias is under 1 Hz (s)
MAX_DEV_FL = 0.6        # largest flicker deviation searched (Hz) = 0.3 Hz at the mains
MIN_ALIAS_HZ = 0.08     # frame-mean path refuses aliases closer to 0 Hz than this
MIN_SNR_DB = 3.0        # per-window tracking SNR needed to keep a point
BAND_SNR_MIN_DB = 6.0   # band contrast (peak vs median across the read-out search) needed for "rolling bands seen"
READOUT_GRID_MS = (4.0, None, 0.5)    # search from 4 ms to the frame period, 0.5 ms steps (then 0.05 ms)


# ----------------------------------------------------------------------------- decoding
def probe_video(path):
    """ffprobe of the first video stream: fps (exact fraction), size, duration, start time, rotation."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration,start_time,codec_name"
                        ":stream_side_data=rotation:stream_tags=rotate", "-of", "json", path],
                       capture_output=True, text=True, timeout=60)
    js = json.loads(r.stdout or "{}")
    st = (js.get("streams") or [None])[0]
    if not st:
        return None
    def frac(s):
        try:
            v = Fraction(s)
            return v if v > 0 else None
        except (ValueError, ZeroDivisionError, TypeError):
            return None
    fps = frac(st.get("avg_frame_rate")) or frac(st.get("r_frame_rate"))
    rot = 0
    for sd in st.get("side_data_list") or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    rot = rot or int((st.get("tags") or {}).get("rotate", 0) or 0)
    ra = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=start_time",
                         "-of", "json", path], capture_output=True, text=True, timeout=60)
    a_st = ((json.loads(ra.stdout or "{}").get("streams") or [{}])[0]).get("start_time")
    return dict(width=int(st.get("width") or 0), height=int(st.get("height") or 0),
                fps=float(fps) if fps else None, fps_exact=str(fps) if fps else None,
                duration=float(st.get("duration") or 0) or None, start_time=float(st.get("start_time") or 0),
                audio_start_time=float(a_st) if a_st not in (None, "N/A") else None,
                codec=st.get("codec_name"), rotation=rot, nb_frames=int(st.get("nb_frames") or 0) or None)


def frame_times(path, max_s=None):
    """Sorted presentation times of the video packets (no decoding)."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time", "-of", "csv=p=0"]
    if max_s:
        cmd += ["-read_intervals", f"%+{float(max_s)}"]
    try:
        o = subprocess.run(cmd + [path], capture_output=True, text=True, timeout=300).stdout
    except Exception:
        return None
    out = []
    for x in o.split():
        try:
            out.append(float(x.strip(",")))
        except ValueError:
            pass
    return np.sort(np.array(out)) if out else None


def timing(info, pts, n):
    """Frame-rate check. Phones often write variable-frame-rate files whose nominal rate (e.g. 30/1) is not the
    true mean rate (e.g. 29.987). A 0.04 % rate error shifts the flicker estimate by tens of mHz, so the mean rate
    is fitted from the packet times. Frame-to-frame jitter is ignored (assumed to be container rounding) [VERIFY]."""
    out = dict(vfr=False, fps_fit=None, jitter_ms=None, max_dev_ms=None)
    if pts is None or len(pts) < 100 or abs(len(pts) - n) > max(3, 0.002 * n):
        return out
    k = np.arange(len(pts))
    a, b = np.polyfit(k, pts, 1)
    res = pts - (a * k + b)
    d = np.diff(pts)
    out.update(fps_fit=float(1.0 / a), jitter_ms=round(float(np.std(d) * 1000), 3),
               max_dev_ms=round(float(np.max(np.abs(res)) * 1000), 2))
    nominal = info.get("fps") or out["fps_fit"]
    out["vfr"] = bool(out["jitter_ms"] > 0.2 or abs(out["fps_fit"] - nominal) / nominal > 2e-5)
    return out


def decode_luma(path, rows=ROWS, cols=COLS, max_s=None, native_height=None):
    """Frames as (N, rows, cols) float32 in 0..1, decoded in sensor orientation (no auto-rotate),
    luma only, 16-bit after area averaging so faint bands are not lost to 8-bit rounding."""
    rows = int(min(rows, native_height or rows))
    cmd = ["ffmpeg", "-v", "error", "-noautorotate", "-i", path, "-map", "0:v:0"]
    if max_s:
        cmd += ["-t", str(float(max_s))]
    cmd += ["-fps_mode", "passthrough", "-vf", f"format=gray16le,scale={cols}:{rows}:flags=area",
            "-f", "rawvideo", "-pix_fmt", "gray16le", "pipe:1"]
    r = subprocess.run(cmd, capture_output=True, timeout=3600)
    if r.returncode != 0:
        raise ValueError("ffmpeg could not decode the video: " + r.stderr.decode(errors="replace")[-300:])
    a = np.frombuffer(r.stdout, dtype="<u2")
    n = a.size // (rows * cols)
    return a[: n * rows * cols].reshape(n, rows, cols).astype(np.float32) / 65535.0


# ----------------------------------------------------------------------------- picture quality
def frame_quality(Y, fps, key_idx=None):
    """Bright/unclipped column mask, per-frame motion score, exposure gain and the frames to drop.
    Motion is measured twice, both after removing the row-common part (flicker bands and exposure are the same
    across a row, so they cancel): frame to previous frame (fast moves) and frame to 1 s earlier (slow pans).
    A one-frame spike exactly on a keyframe is the codec refreshing the picture, not motion, and is ignored."""
    M = Y.mean(0)
    col_mean = M.mean(0)
    bright_px = (M > 0.06) & (M < 0.92)
    L = np.log(Y + 1e-3)
    w = bright_px

    def score(D):
        R = D - np.median(D, axis=2, keepdims=True)
        return np.array([np.mean(np.abs(r[w])) if w.any() else 0.0 for r in R])
    motion = np.concatenate([[0.0], score(np.diff(L, axis=0))])
    med = float(np.median(motion[1:])) if len(motion) > 1 else 0.0
    moving = motion > (3.0 * med + 0.01)
    if key_idx is not None and len(key_idx) and moving.any():
        kk = np.zeros(len(moving), bool)
        kk[np.asarray([k for k in key_idx if 0 <= k < len(moving)], int)] = True
        iso = moving & kk & ~np.roll(moving, 1) & ~np.roll(moving, -1)
        moving = moving & ~iso
    m1 = max(1, int(round(fps)))
    slow = np.zeros(len(Y))
    if len(Y) > m1:
        slow[m1:] = score(L[m1:] - L[:-m1])
        meds = float(np.median(slow[m1:]))
        mv2 = slow > (3.0 * meds + 0.02)
        # a pan seen 1 s later marks the frames in between too
        mv2 = np.convolve(mv2.astype(float), np.r_[np.zeros(m1), np.ones(m1 + 1)], "same") > 0
        moving = moving | mv2
    gain = np.array([np.median(y[bright_px] / M[bright_px]) if bright_px.any() else 1.0 for y in Y])
    dg = np.abs(np.diff(np.log(np.maximum(gain, 1e-6)), prepend=np.log(max(gain[0], 1e-6))))
    rs = 1.4826 * float(np.median(np.abs(dg - np.median(dg)))) + 1e-9
    jump = dg > max(0.03, 8 * rs)
    bad = moving | jump
    k = max(1, int(round(0.2 * fps)))                       # pad each event by 0.2 s
    if bad.any():
        bad = np.convolve(bad.astype(float), np.ones(2 * k + 1), "same") > 0
    cols_ok = (col_mean > 0.06) & (col_mean < 0.92) & (bright_px.mean(0) > 0.5)
    return dict(motion=motion, motion_1s=slow, moving=moving, gain=gain, jump=jump, bad=bad, cols_ok=cols_ok, bright_px=bright_px)


def segments(bad, fps, min_s=MIN_SEG_S):
    """Runs of good frames, split at motion and exposure events."""
    out, i, n = [], 0, len(bad)
    while i < n:
        if bad[i]:
            i += 1
            continue
        j = i
        while j < n and not bad[j]:
            j += 1
        if (j - i) / fps >= min_s:
            out.append((i, j))
        i = j
    return out


def _running_bg(X, fps, chunk_s=BG_CHUNK_S):
    """Slow static-scene background of X (n, ...): chunk means, linearly interpolated per frame."""
    n = len(X)
    c = max(2, int(round(chunk_s * fps)))
    if n <= c:
        return np.broadcast_to(X.mean(0), X.shape)
    edges = list(range(0, n, c))
    if n - edges[-1] < c // 2 and len(edges) > 1:
        edges.pop()
    bounds = edges + [n]
    means = np.stack([X[a:b].mean(0) for a, b in zip(bounds[:-1], bounds[1:])])
    if len(means) < 2:
        return np.broadcast_to(means[0], X.shape)
    centers = np.array([(a + b - 1) / 2 for a, b in zip(bounds[:-1], bounds[1:])])
    idx = np.arange(n)
    j = np.clip(np.searchsorted(centers, idx) - 1, 0, len(centers) - 2)
    fr = np.clip((idx - centers[j]) / (centers[j + 1] - centers[j]), 0, 1)
    sh = (n,) + (1,) * (X.ndim - 1)
    return means[j] * (1 - fr).reshape(sh) + means[j + 1] * fr.reshape(sh)


def column_select(Y, q, fps):
    """Columns used for the row signal: bright, unclipped and quiet (static) after removing the row-common part."""
    ok = q["cols_ok"].copy()
    if ok.sum() < 2:
        ok = q["bright_px"].mean(0) > 0.2
    if ok.sum() < 1:
        ok[:] = True
    good = ~q["bad"]
    if good.sum() > 10:
        Z = Y[good][:, :, ok]
        S = Z / (_running_bg(Z, fps) + 1e-6) - 1
        R = S - np.median(S, axis=2, keepdims=True)
        v = np.sqrt(np.mean(R ** 2, axis=(0, 1)))
        keep = v <= 2.0 * np.median(v) + 1e-9
        idx = np.where(ok)[0]
        ok = np.zeros_like(ok)
        ok[idx[keep]] = True
    return ok


def row_signals(Y, q, cols, fps, segs, normalise_gain=False):
    """Per-frame row profile s_k(r) = brightness / slow background - 1, averaged over the chosen columns.
    NaN rows for dropped frames. Also returns the frame-mean series m_k.
    No per-frame gain normalisation by default: the frame gain itself carries the aliased flicker, and dividing
    by it would put sidebands on the band phase. A gain change only scales the bands, and the fit's constant
    term absorbs the offset; sudden exposure jumps split the stretches instead."""
    n, H, _ = Y.shape
    S = np.full((n, H), np.nan, np.float32)
    m = np.full(n, np.nan)
    for a, b in segs:
        Z = Y[a:b][:, :, cols].mean(2)                         # (len, H)
        B = _running_bg(Z, fps)
        s = Z / (B + 1e-6) - 1
        m[a:b] = s.mean(1)
        if normalise_gain:
            s = (Z / (q["gain"][a:b, None] + 1e-9)) / (_running_bg(Z / (q["gain"][a:b, None] + 1e-9), fps) + 1e-6) - 1
        S[a:b] = s
    return S, m


# ----------------------------------------------------------------------------- rolling shutter
def _design(H, kappa):
    """Least-squares design across rows: constant, tilt, cos, sin at kappa cycles per frame height."""
    r = (np.arange(H) + 0.5) / H
    return np.stack([np.ones(H), r - 0.5, np.cos(2 * np.pi * kappa * r), np.sin(2 * np.pi * kappa * r)], 1)


def band_gram(H, kappa):
    """Gram matrix (per row) of the cos/sin regressors after removing constant and tilt. The energy a band
    amplitude explains is [a b] G [a b]^T, which keeps scores comparable across kappa (near kappa = 0 the
    sinusoid is almost a constant, so raw amplitudes blow up)."""
    X = _design(H, kappa)
    Q, _ = np.linalg.qr(X[:, :2])
    R = X[:, 2:] - Q @ (Q.T @ X[:, 2:])
    return R.T @ R / H


def fit_bands(S, kappa):
    """Complex band amplitude per frame: s_k(r) ~ Re(A_k exp(i 2 pi kappa r))."""
    X = _design(S.shape[1], kappa)
    P = np.linalg.pinv(X)
    ok = np.isfinite(S).all(1)
    C = np.full((len(S), 4), np.nan)
    C[ok] = S[ok] @ P.T
    return C[:, 2] - 1j * C[:, 3]


def band_energy(A, H, kappa):
    """Per-frame energy explained by the band amplitudes A at kappa."""
    G = band_gram(H, kappa)
    a, b = A.real, -A.imag
    return G[0, 0] * a * a + 2 * G[0, 1] * a * b + G[1, 1] * b * b


def band_amplitudes(S, segs, kappa, fps):
    """fit_bands, then the slow static part of the band amplitude is removed per stretch (what is left of the
    scene after the background division projects onto the sinusoid as a near-constant)."""
    A = fit_bands(S, kappa)
    out = np.full(len(A), np.nan + 0j)
    for a, b in segs:
        x = A[a:b]
        out[a:b] = x - _running_bg(x, fps)
    return out


def readout_search(S, segs, fps, f_ref=120.0, lo_ms=READOUT_GRID_MS[0], step_ms=0.5):
    """Band contrast vs read-out time. Bands repeat kappa = f_flicker * readout times per frame height, so
    the search runs over kappa (coarse 0.5 ms grid at f_ref, then 0.05 ms around the best). Returns the
    curve, the best kappa and the contrast in dB (peak over the median of the curve)."""
    if not segs:
        return None
    hi_ms = 1000.0 / fps
    def power(k):
        A = band_amplitudes(S, segs, k, fps)
        return float(np.nanmean(band_energy(A, S.shape[1], k)))
    ms = np.arange(lo_ms, hi_ms + 1e-9, step_ms)
    kap = ms / 1000.0 * f_ref
    pdb = np.array([10 * np.log10(power(k) + 1e-30) for k in kap])
    j = int(np.argmax(pdb))
    fine = np.arange(max(lo_ms, ms[j] - step_ms), min(hi_ms, ms[j] + step_ms) + 1e-9, 0.05) / 1000.0 * f_ref
    pf = np.array([10 * np.log10(power(k) + 1e-30) for k in fine])
    kb = float(fine[int(np.argmax(pf))])
    contrast = float(max(pf.max(), pdb[j]) - np.median(pdb))
    return dict(readout_ms_grid=[round(float(v), 3) for v in ms], power_db=[round(float(v), 2) for v in pdb],
                f_ref=f_ref, best_kappa=kb, contrast_db=round(contrast, 2),
                readout_ms={"60": round(kb / 120.0 * 1000, 3), "50": round(kb / 100.0 * 1000, 3)})


# ----------------------------------------------------------------------------- temporal tracking
def track(z, fps, centre_hz, half_hz, win_s, t_offset=0.0, complex_in=True, pad=8):
    """Per-second peak frequency of z (frames, NaN = dropped) near centre_hz, by zero-padded FFT + QIFFT.
    Returns t (s, window centres), f_obs (Hz), snr_db."""
    n = len(z)
    nw = int(round(win_s * fps))
    if n < nw:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    nfft = 1 << int(np.ceil(np.log2(nw * pad)))
    freqs = np.fft.fftfreq(nfft, 1 / fps)
    if not complex_in:
        freqs = np.abs(freqs)
    band = np.where(np.abs(freqs - centre_hz) <= half_hz)[0]
    if not complex_in:
        band = band[(freqs[band] > 0.02) & (freqs[band] < fps / 2 - 0.05)]
    if len(band) < 3:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    order = band[np.argsort(freqs[band])]
    win = np.hanning(nw)
    dur = n / fps
    T = np.arange(win_s / 2, dur - win_s / 2 + 1e-9, 1.0)
    F = np.full(len(T), np.nan)
    SN = np.full(len(T), np.nan)
    valid = np.isfinite(z)
    zz = np.where(valid, z, 0)
    for i, tc in enumerate(T):
        a = int(round((tc - win_s / 2) * fps))
        seg = zz[a:a + nw]
        if len(seg) < nw or valid[a:a + nw].mean() < 0.6:
            continue
        seg = seg - (seg[valid[a:a + nw]].mean() if not complex_in else 0)
        P = np.abs(np.fft.fft(seg * win, nfft)) ** 2
        pb = P[order]
        j = int(np.argmax(pb))
        noise = float(np.median(pb)) + 1e-30
        SN[i] = 10 * np.log10(pb[j] / noise)
        if 0 < j < len(pb) - 1:
            la, lb, lc = np.log(pb[j - 1] + 1e-30), np.log(pb[j] + 1e-30), np.log(pb[j + 1] + 1e-30)
            den = la - 2 * lb + lc
            d = 0.5 * (la - lc) / den if den < 0 else 0.0
        else:
            d = 0.0
        df = freqs[order[1]] - freqs[order[0]]
        F[i] = freqs[order[j]] + d * df
    return T + t_offset, F, SN


def track_phase(w, fps, win_s, t_offset=0.0, smooth_s=0.5):
    """Per-second frequency of a slowly rotating complex phasor w (frames; NaN = dropped) from the slope of its
    unwrapped phase in a window (weighted by amplitude). SNR from the leftover phase scatter:
    snr_db = 10 log10(1 / (2 var)), so a random phase (var = pi^2 / 3) gives about -8 dB."""
    n = len(w)
    nw = int(round(win_s * fps))
    if n < nw:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    k = max(1, int(round(smooth_s * fps)))
    valid = np.isfinite(w)
    num = np.convolve(np.where(valid, w, 0), np.ones(k), "same")
    den = np.convolve(valid.astype(float), np.ones(k), "same")
    sm = np.where(den >= 0.6 * k, num / np.maximum(den, 1e-9), np.nan + 0j)
    ok = np.isfinite(sm)
    ph = np.full(n, np.nan)
    i = 0
    while i < n:                                   # unwrap each contiguous run on its own
        if not ok[i]:
            i += 1; continue
        j = i
        while j < n and ok[j]:
            j += 1
        ph[i:j] = np.unwrap(np.angle(sm[i:j]))
        i = j
    tk = np.arange(n) / fps
    amp = np.abs(np.nan_to_num(sm))
    T = np.arange(win_s / 2, n / fps - win_s / 2 + 1e-9, 1.0)
    F = np.full(len(T), np.nan); SN = np.full(len(T), np.nan)
    run_id = np.cumsum(~ok)
    for m, tc in enumerate(T):
        a = int(round((tc - win_s / 2) * fps)); b = a + nw
        sel = ok[a:b]
        if sel.mean() < 0.6:
            continue
        rid = run_id[a:b][sel]
        main = np.bincount(rid).argmax()            # use the longest unwrapped run in the window
        use = np.zeros(b - a, bool); use[np.where(sel)[0][rid == main]] = True
        if use.sum() < 0.5 * nw:
            continue
        x = tk[a:b][use]; y = ph[a:b][use]; wt = amp[a:b][use] + 1e-12
        p = np.polyfit(x, y, 1, w=np.sqrt(wt))
        res = np.angle(np.exp(1j * (y - np.polyval(p, x))))
        var = float(np.average(res ** 2, weights=wt))
        F[m] = p[0] / (2 * np.pi)
        SN[m] = 10 * np.log10(1.0 / (2 * var + 1e-6))
    return T + t_offset, F, SN


def _trace(t, f_mains, snr, nominal, win_s, note):
    f = np.where(np.isfinite(snr) & (snr >= MIN_SNR_DB), f_mains, np.nan)
    if np.isfinite(f).sum() > 20:
        f = despike(f)
    med = float(np.nanmedian(snr)) if np.isfinite(snr).any() else 0.0
    tr = EnfTrace(t=np.asarray(t, float), f=f, snr_db=np.asarray(snr, float), nominal=int(nominal),
                  harmonics_used=[2], harmonic_snr_db={2: med}, harmonic_corr={2: 1.0}, per_harmonic={2: f},
                  frame_s=float(win_s), hop_s=1.0)
    tr.source = note
    return tr


def keyframe_times(path, max_s=None):
    """Presentation times of keyframes (I-frames) of the first video stream, from ffprobe; [] if unknown."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
           "-show_entries", "frame=pts_time", "-of", "csv=p=0"]
    if max_s:
        cmd += ["-read_intervals", f"%+{float(max_s)}"]
    try:
        o = subprocess.run(cmd + [path], capture_output=True, text=True, timeout=300).stdout
    except Exception:
        return []
    out = []
    for x in o.split():
        x = x.strip(",")
        try:
            out.append(float(x))
        except ValueError:
            pass
    return out


def gop_pumping(m, fps, key_t):
    """Codec 'keyframe pumping': brightness steps at every keyframe that repeat at 1/GOP seconds.
    Returns dict(gop_s, f_gop, harm_db[1..4]) where harm_db is the peak power at k/GOP over the median
    in 0.05-2 Hz of the frame-mean series. A clean flicker sinusoid has no power at 3/GOP and 4/GOP,
    pumping (a sawtooth-like pattern) does. Heuristic, tuned on simulated x264 clips [VERIFY on real cameras]."""
    if len(key_t) < 4:
        return None
    gi = np.diff(np.asarray(key_t, float))
    gi = gi[gi > 0]
    if not len(gi) or np.std(gi) > 0.05 * np.median(gi):
        return dict(gop_s=float(np.median(gi)) if len(gi) else None, f_gop=None, harm_db=None, regular=False)
    g = float(np.median(gi))
    x = np.nan_to_num(np.asarray(m, float) - np.nanmean(m))
    N = len(x)
    F = np.fft.rfftfreq(4 * N, 1 / fps)
    P = np.abs(np.fft.rfft(x * np.hanning(N), 4 * N)) ** 2
    band = (F > 0.05) & (F < 2)
    noise = float(np.median(P[band])) + 1e-30
    df = F[1]
    def pk(f):
        j = int(round(f / df))
        return float(P[max(0, j - 3):j + 4].max()) if j + 4 < len(P) else noise
    return dict(gop_s=round(g, 3), f_gop=round(1 / g, 4), regular=True,
                harm_db=[round(10 * np.log10(max(pk(k / g), 1e-30) / noise), 1) for k in range(1, 5)])


PUMP_HARM_DB = 8.0     # 3rd/4th keyframe harmonic this far over the noise ...
PUMP_REL_DB = 20.0     # ... and no more than this far below the 1st: a sawtooth-like pattern, not a lone sinusoid


def pump_present(pump):
    if not pump or not pump.get("harm_db"):
        return False
    h = pump["harm_db"]
    return max(h[2:]) >= PUMP_HARM_DB and max(h[2:]) >= h[0] - PUMP_REL_DB


GOP_DECOUPLE = True


def _remove_gop_offsets(A, key_t, fps, a0):
    """Codec offsets: each group of pictures (keyframe to keyframe) adds its own small, fixed pattern to the band fit.
    In A that pattern does not rotate, while the flicker rotates at the alias a0 (A is sampled once per frame).
    When a GOP spans at least ~0.9 alias cycles, subtracting each GOP's mean removes the codec pattern and costs the
    flicker little. Otherwise (e.g. exactly 30 fps on 60 Hz, alias ~0) the two cannot be separated and A is left alone."""
    if not GOP_DECOUPLE or not key_t or len(key_t) < 3:
        return A, None
    ki = np.unique(np.clip(np.round(np.asarray(key_t) * fps).astype(int), 0, len(A)))
    gi = np.diff(ki)
    if not len(gi) or abs(a0) * np.median(gi) / fps < 0.9:
        return A, None
    B = A.copy()
    bounds = list(ki) + [len(A)]
    if bounds[0] > 0:
        bounds = [0] + bounds
    for a, b in zip(bounds[:-1], bounds[1:]):
        seg = B[a:b]
        ok = np.isfinite(seg)
        if ok.sum() >= 0.5 * (b - a) and b - a > 1:
            B[a:b] = seg - seg[ok].mean()
    return B, "per-GOP offsets removed"


def alias_of(f_fl, fps):
    """Signed alias of a flicker frequency at a frame rate, in (-fps/2, fps/2]."""
    a = f_fl - round(f_fl / fps) * fps
    return float(a)


# ----------------------------------------------------------------------------- main entry
def analyze_video(path, nominal=None, readout_ms=None, log=None, max_s=None, mode="auto"):
    """Light-flicker ENF from the picture. Returns a dict with status, the chosen path, the trace
    (EnfTrace under '_trace'), presence verdict and diagnostics. Never raises for 'no flicker'."""
    from .extract import detect_enf
    log = log or (lambda m: None)
    info = probe_video(path)
    if not info or not info.get("fps"):
        return dict(available=False, status="no video stream found", path_used=None)
    fps = info["fps"]
    log(f"video: {info['width']}x{info['height']} at {info['fps_exact']} fps ({fps:.3f}), codec {info['codec']}"
        + (f", rotation {info['rotation']} deg (read in sensor orientation)" if info["rotation"] else ""))
    Y = decode_luma(path, max_s=max_s, native_height=info["height"] or None)
    n = len(Y)
    tm = timing(info, frame_times(path, max_s=max_s), n)
    info["timing"] = tm
    if tm["vfr"] and tm["fps_fit"]:
        log(f"video: variable frame rate (nominal {info['fps_exact']}, measured mean {tm['fps_fit']:.4f} fps, "
            f"frame-time jitter {tm['jitter_ms']} ms): using the measured mean rate")
        fps = tm["fps_fit"]
        info["fps_used"] = fps
    if n < fps * MIN_CLIP_S:
        return dict(available=True, status=f"video too short for flicker ENF ({n / fps:.0f} s; need {MIN_CLIP_S} s or more)",
                    path_used=None, info=info, presence=dict(verdict="absent", reasons=["too short"]))
    t_off = info["start_time"] - (info["audio_start_time"] if info["audio_start_time"] is not None else info["start_time"])
    key_t = keyframe_times(path, max_s=max_s)
    q = frame_quality(Y, fps, key_idx=np.round(np.asarray(key_t) * fps).astype(int) if key_t else None)
    segs = segments(q["bad"], fps)
    dropped = float(1 - sum(b - a for a, b in segs) / n)
    log(f"video: {n} frames; dropped {100 * dropped:.0f} % (camera motion {100 * q['moving'].mean():.0f} %, "
        f"exposure jumps {int(q['jump'].sum())}); {len(segs)} usable stretch(es)")
    if not segs:
        return dict(available=True, status="no static stretch long enough (camera moving or exposure changing)",
                    path_used=None, info=info, dropped=dropped, presence=dict(verdict="absent", reasons=["no static stretch"]))
    cols = column_select(Y, q, fps)
    S, mser = row_signals(Y, q, cols, fps, segs)
    del Y
    noms = [int(nominal)] if nominal else [60, 50]
    pump = gop_pumping(mser, fps, key_t)
    if pump and pump.get("harm_db"):
        log(f"video: keyframe every {pump['gop_s']} s ({pump['f_gop']} Hz); keyframe harmonics over noise "
            f"{pump['harm_db']} dB")
    cands = []
    # ---- rolling-shutter path
    rs = None if readout_ms else readout_search(S, segs, fps)
    for nom in noms:
        f_fl = 2.0 * nom
        if readout_ms:
            kappa, ro_src = f_fl * readout_ms / 1000.0, "entered"
        elif rs:
            kappa, ro_src = rs["best_kappa"], "searched"      # band spacing is what is measured; ms depends on nominal
        else:
            continue
        ro = kappa / f_fl * 1000.0
        if ro > 1000.0 / fps * 1.05 or ro <= 0:
            continue
        A = band_amplitudes(S, segs, kappa, fps)
        A, gop_note = _remove_gop_offsets(A, key_t, fps, alias_of(f_fl, fps))
        tk = np.arange(n) / fps
        w = A * np.exp(-2j * np.pi * f_fl * tk)
        t, fo, sn = track_phase(w, fps, WIN_RS, t_offset=t_off)
        fo = np.where(np.abs(fo) <= MAX_DEV_FL, fo, np.nan)
        tr = _trace(t, nom + fo / 2.0, sn, nom, WIN_RS, "video: rolling shutter")
        det = detect_enf(tr)
        cands.append(dict(path="rolling shutter", nominal=nom, readout_ms=round(ro, 3), readout_source=ro_src,
                          idle_ms=round(1000.0 / fps - ro, 3), kappa=round(kappa, 4), trace=tr, detect=det,
                          snr=float(np.nanmedian(sn)) if np.isfinite(sn).any() else -99))
    # ---- frame-mean path
    for nom in noms:
        f_fl = 2.0 * nom
        a0 = alias_of(f_fl, fps)
        if abs(a0) < MIN_ALIAS_HZ:
            cands.append(dict(path="frame mean", nominal=nom, alias_hz=round(a0, 4), trace=None,
                              detect=dict(verdict="absent", score=0.0, reasons=[
                                  f"at {fps:.3f} fps the {f_fl:.0f} Hz flicker aliases to {a0:.3f} Hz, too close to 0 Hz to track"]),
                              snr=-99))
            continue
        if pump_present(pump):
            near = [k for k in range(1, 9) if abs(k * pump["f_gop"] - abs(a0)) <= 0.06]
            if near:
                cands.append(dict(path="frame mean", nominal=nom, alias_hz=round(a0, 4), trace=None, snr=-99,
                                  detect=dict(verdict="absent", score=0.0, reasons=[
                                      f"the aliased flicker ({abs(a0):.3f} Hz) sits on the codec's keyframe rhythm "
                                      f"({near[0]} x {pump['f_gop']} Hz, a keyframe every {pump['gop_s']} s) and keyframe "
                                      f"brightness pumping is present ({max(pump['harm_db'][2:]):.0f} dB): the two cannot be told apart"])))
                continue
        win = WIN_FM_SLOW if abs(a0) < 1.0 else WIN_RS
        t, fo, sn = track(mser, fps, abs(a0), min(MAX_DEV_FL, abs(a0) - 0.03 if abs(a0) < 0.65 else MAX_DEV_FL), win,
                          t_offset=t_off, complex_in=False)
        f_fl_est = np.where(a0 >= 0, f_fl - a0 + fo, f_fl + abs(a0) - fo) if len(fo) else fo
        tr = _trace(t, f_fl_est / 2.0, sn, nom, win, "video: frame mean (aliased)")
        det = detect_enf(tr)
        cands.append(dict(path="frame mean", nominal=nom, alias_hz=round(a0, 4), trace=tr, detect=det,
                          snr=float(np.nanmedian(sn)) if np.isfinite(sn).any() else -99))
    rank = {"present": 2, "weak": 1, "absent": 0}
    cands_ok = [c for c in cands if c.get("trace") is not None]
    best = max(cands_ok, key=lambda c: (rank[c["detect"]["verdict"]], c["detect"].get("score", 0), c["snr"]), default=None)
    band_seen = bool(rs and rs["contrast_db"] >= BAND_SNR_MIN_DB) if not readout_ms else None
    reasons = []
    verdict = best["detect"]["verdict"] if best else "absent"
    if best is not None and best["path"] == "rolling shutter" and band_seen and verdict == "weak" \
            and best["detect"].get("score", 0) >= 0.55 and not best["detect"].get("flat"):
        # a second, independent cue: the bands themselves stand out in the read-out search
        verdict = "present"
        reasons.append(f"rolling bands stand out in the read-out search ({rs['contrast_db']:.1f} dB): counts as a second cue")
    if best is not None:
        reasons += [f"{best['path']} path at {best['nominal']} Hz mains: " + "; ".join(best["detect"]["reasons"][:4])]
        if best["path"] == "rolling shutter" and not band_seen and best.get("readout_source") == "searched":
            reasons.append(f"rolling bands not clearly seen (contrast {rs['contrast_db'] if rs else 0:.1f} dB < "
                           f"{BAND_SNR_MIN_DB:.0f} dB): read-out time is a guess")
            verdict = {"present": "weak", "weak": "absent"}.get(verdict, verdict)
        if best["trace"].valid_fraction() < 0.3:
            reasons.append(f"only {100 * best['trace'].valid_fraction():.0f} % of seconds tracked")
            verdict = "absent" if verdict != "present" else "weak"
    else:
        reasons.append("no usable flicker path")
    status = {"present": "light flicker found", "weak": "weak light flicker (use with care)",
              "absent": "no usable light flicker (abstain)"}[verdict]
    log(f"video flicker: {status}" + (f" via {best['path']} ({best['nominal']} Hz)" if best else ""))
    out = dict(available=True, status=status, info=info, dropped=round(dropped, 3), n_frames=int(n),
               n_segments=len(segs), columns_used=int(cols.sum()), readout_search=rs, band_seen=band_seen,
               keyframes=pump,
               presence=dict(verdict=verdict, reasons=reasons),
               candidates=[{k: v for k, v in c.items() if k != "trace"} for c in cands],
               path_used=best["path"] if best else None, nominal=best["nominal"] if best else None,
               readout_ms=best.get("readout_ms") if best else None,
               readout_source=best.get("readout_source") if best else None,
               alias_hz=best.get("alias_hz") if best else None,
               detect=best["detect"] if best else None)
    out["_trace"] = best["trace"] if best and verdict != "absent" else None
    out["_trace_any"] = best["trace"] if best else None
    return out


# ----------------------------------------------------------------------------- audio vs picture
def _grid1s(tr):
    from .match import trace_on_grid
    return trace_on_grid(tr), float(tr.t[0])


def av_agreement(atr, vtr, a_det=None, v_det=None, max_lag_s=10, seg_s=None):
    """Do the audio hum and the light flicker follow the same grid wander? Returns r, best lag, offset,
    per-piece agreement and a verdict with a splice/tamper hint when they disagree."""
    if atr is None or vtr is None:
        return dict(verdict="not comparable", reason="need both an audio and a video ENF trace")
    qa, ta = _grid1s(atr)
    qv, tv = _grid1s(vtr)
    t0 = int(np.floor(min(ta, tv)))
    t1 = int(np.ceil(max(ta + len(qa), tv + len(qv))))
    A = np.full(t1 - t0, np.nan); V = np.full(t1 - t0, np.nan)
    A[int(round(ta)) - t0:int(round(ta)) - t0 + len(qa)] = qa
    V[int(round(tv)) - t0:int(round(tv)) - t0 + len(qv)] = qv
    k = int(round(max(atr.frame_s, vtr.frame_s)))
    def sm(x):
        ok = np.isfinite(x).astype(float)
        num = np.convolve(np.nan_to_num(x), np.ones(k), "same"); den = np.convolve(ok, np.ones(k), "same")
        return np.where(den >= k * 0.6, num / np.maximum(den, 1e-9), np.nan)
    A, V = sm(A), sm(V)
    def corr(a, b, nmin=60):
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < nmin or np.std(a[ok]) == 0 or np.std(b[ok]) == 0:
            return np.nan, int(ok.sum())
        return float(np.corrcoef(a[ok], b[ok])[0, 1]), int(ok.sum())
    best = (np.nan, 0, 0)
    for L in range(-max_lag_s, max_lag_s + 1):
        b = np.roll(V, L)
        if L > 0: b[:L] = np.nan
        elif L < 0: b[L:] = np.nan
        r, nn = corr(A, b)
        if np.isfinite(r) and (not np.isfinite(best[0]) or r > best[0]):
            best = (r, L, nn)
    r0, n0 = corr(A, V)
    ok = np.isfinite(A) & np.isfinite(V)
    off = float(np.nanmedian(A[ok] - V[ok]) * 1000) if ok.any() else None
    if seg_s is None:                                  # 1-minute pieces for short clips, 2-minute for long ones
        seg_s = 60 if ok.sum() < 900 else 120
    Vl = V
    if np.isfinite(best[0]) and best[1]:            # pieces are compared at the best lag (a sync shift is not a splice)
        L = best[1]
        Vl = np.roll(V, L)
        if L > 0: Vl[:L] = np.nan
        else: Vl[L:] = np.nan
    pieces = []
    for a in range(0, len(A) - seg_s + 1, seg_s):
        r, nn = corr(A[a:a + seg_s], Vl[a:a + seg_s], nmin=int(0.6 * seg_s))
        pieces.append(dict(t=a + t0, r=None if not np.isfinite(r) else round(r, 3), n=nn))
    rb, lag = best[0], best[1]
    both_present = (a_det or {}).get("verdict") == "present" and (v_det or {}).get("verdict") == "present"
    good = [p for p in pieces if p["r"] is not None and p["r"] >= 0.6]
    badp = [p for p in pieces if p["r"] is not None and p["r"] < 0.3]
    if not np.isfinite(rb) or best[2] < 120:
        verdict, hint = "not comparable", "less than 2 minutes where both traces are usable"
    elif both_present and good and badp:
        verdict, hint = "partly disagree", ("some pieces agree and others do not (pieces starting at "
                                            + ", ".join(f"{p['t']} s" for p in badp[:4]) + " disagree): possible splice or replaced section")
    elif rb >= 0.7 and abs(lag) <= 2 and abs(off or 0) <= 10:
        verdict, hint = "agree", "audio hum and light flicker follow the same grid wander: consistent with one recording"
    elif rb >= 0.7:
        verdict, hint = "agree with an offset", (f"same grid wander, but shifted by {lag:+d} s" if abs(lag) > 2 else
                                                 f"same wander but {off:+.0f} mHz apart") + \
            ": an audio/video sync offset, or the sound was re-laid. Check the edit history"
    elif both_present and rb < 0.4:
        verdict, hint = "disagree", ("both carry clear mains ENF but it does not line up: the sound and the picture may "
                                     "come from different times or places (splice / dub / tamper hint)")
    else:
        verdict, hint = "inconclusive", "the traces are too noisy to say"
    return dict(verdict=verdict, hint=hint, r_lag0=None if not np.isfinite(r0) else round(r0, 3),
                r_best=None if not np.isfinite(rb) else round(rb, 3), best_lag_s=int(lag), overlap_s=int(best[2]),
                offset_mhz=None if off is None else round(off, 2), pieces=pieces, piece_s=int(seg_s), smoothing_s=k,
                _A=A, _V=V, _t0=t0)
