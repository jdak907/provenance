"""Spectrogram, normalisation, ridge tracing and event detection."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal
from scipy.io import wavfile
from scipy.ndimage import maximum_filter1d, uniform_filter1d


def load_audio(path: str):
    """Load WAV directly. Other formats (mp3, mp4, m4a) are converted with ffmpeg."""
    import os
    import subprocess
    import tempfile

    if not path.lower().endswith(".wav"):
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ac", "1",
                        "-ar", "8000", tmp], check=True)
        path_to_read, cleanup = tmp, tmp
    else:
        path_to_read, cleanup = path, None
    sr, x = wavfile.read(path_to_read)
    if cleanup:
        os.unlink(cleanup)
    x = x.astype(np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    peak = np.max(np.abs(x)) or 1.0
    return sr, x / peak


@dataclass
class Spectrogram:
    t: np.ndarray        # frame centre times, seconds from start of audio
    f: np.ndarray        # bin frequencies, Hz
    db: np.ndarray       # power in dB, shape (F, T)
    bright: np.ndarray   # normalised "brightness" >= 0, shape (F, T)

    @property
    def hop(self) -> float:
        return float(self.t[1] - self.t[0])

    @property
    def df(self) -> float:
        return float(self.f[1] - self.f[0])


def compute(x, sr, fmin=30.0, fmax=400.0, win_s=1.0, hop_s=0.25, work_sr=1000,
            steady_window_s: float | None = 60.0) -> Spectrogram:
    """Zoom into the low band and use a long window for fine frequency resolution.

    The video's point: the curve is invisible until you zoom to the right band
    and raise the resolution.
    """
    if sr > work_sr:
        g = np.gcd(int(sr), int(work_sr))
        x = signal.resample_poly(x, work_sr // g, int(sr) // g)
        sr = work_sr
    nper = int(round(win_s * sr))
    hop = int(round(hop_s * sr))
    f, t, Z = signal.stft(x, fs=sr, window="hann", nperseg=nper, noverlap=nper - hop,
                          nfft=4 * nper, boundary=None, padded=False)
    P = np.abs(Z) ** 2
    keep = (f >= fmin) & (f <= fmax)
    f, P = f[keep], P[keep]
    db = 10 * np.log10(P + 1e-20)
    return Spectrogram(t=t, f=f, db=db, bright=normalise(db, hop_s, steady_window_s))


def steady_floor(db, hop_s: float, window_s: float = 60.0):
    """Per-frequency running median over time: the level of tones that sit still.

    Hums, fans and HVAC lines stay in one frequency bin for a long time; a Doppler
    curve sweeps through a bin in seconds. Subtracting this floor removes the former
    and keeps the latter, even when the hum switches on and off during the clip.
    Computed on 1-second blocks for speed, then stretched back to frame rate.
    """
    from scipy.ndimage import median_filter

    k = max(1, int(round(1.0 / hop_s)))
    F, T = db.shape
    nb = int(np.ceil(T / k))
    pad = nb * k - T
    blk = np.pad(db, ((0, 0), (0, pad)), mode="edge").reshape(F, nb, k).mean(axis=2)
    w = max(3, int(round(window_s)))
    if w >= nb:
        floor_b = np.median(blk, axis=1, keepdims=True).repeat(nb, axis=1)
    else:
        floor_b = median_filter(blk, size=(1, w), mode="reflect")
    return np.repeat(floor_b, k, axis=1)[:, :T]


def normalise(db, hop_s: float = 0.25, steady_window_s: float | None = 60.0):
    """Remove stationary tones and scale to robust z-scores, clipped at zero.

    steady_window_s=None falls back to one median per frequency for the whole clip
    (the original behaviour, which leaves part-time hums in place).
    """
    if steady_window_s:
        d = db - steady_floor(db, hop_s, steady_window_s)
    else:
        d = db - np.median(db, axis=1, keepdims=True)
    mad = np.median(np.abs(d)) * 1.4826 + 1e-9
    z = d / mad
    z = uniform_filter1d(z, 3, axis=0)
    return np.clip(z, 0, None)


def trace_ridge(spec: Spectrogram, t0: float, t1: float, fmin=None, fmax=None,
                max_jump_hz: float = 4.0, penalty: float = 0.5):
    """Dynamic-programming ridge trace (the brightest smooth path) inside a time window.

    Returns frame times, ridge frequency and ridge brightness.
    """
    tm = (spec.t >= t0) & (spec.t <= t1)
    fm = np.ones_like(spec.f, dtype=bool)
    if fmin is not None:
        fm &= spec.f >= fmin
    if fmax is not None:
        fm &= spec.f <= fmax
    full = spec.bright[:, tm]
    # Harmonic support: a propeller's fundamental has its 2nd harmonic at twice the
    # frequency, so adding half of B(2f) keeps the trace on the fundamental instead of
    # wandering up to a harmonic when the fundamental fades.
    f2 = np.rint((2 * spec.f[fm] - spec.f[0]) / spec.df).astype(int)
    ok2 = f2 < full.shape[0]
    B = full[fm].copy()
    B[ok2] += 0.5 * full[f2[ok2]]
    freqs = spec.f[fm]
    times = spec.t[tm]
    F, T = B.shape
    k = max(1, int(round(max_jump_hz / spec.df)))
    score = B[:, 0].copy()
    back = np.zeros((F, T), dtype=np.int32)
    offs = np.arange(-k, k + 1)
    idx = np.arange(F)
    for j in range(1, T):
        cand = np.full((len(offs), F), -np.inf)
        for n, o in enumerate(offs):
            src = idx + o
            ok = (src >= 0) & (src < F)
            cand[n, ok] = score[src[ok]] - penalty * abs(o) / k
        best = np.argmax(cand, axis=0)
        back[:, j] = idx + offs[best]
        score = cand[best, idx] + B[:, j]
    path = np.zeros(T, dtype=int)
    path[-1] = int(np.argmax(score))
    for j in range(T - 1, 0, -1):
        path[j - 1] = back[path[j], j]
    rows = np.nonzero(fm)[0][path]
    return times, freqs[path], full[rows, np.arange(T)]


def detect_events(spec: Spectrogram, k_mad: float = 6.0, min_dur_s: float = 15.0,
                  merge_gap_s: float = 20.0, smooth_s: float = 4.0, pad_s: float = 40.0):
    """Find stretches where a tonal ridge stands out from the noise (likely flyovers).

    The threshold adapts to the recording: median plus k_mad robust deviations of the
    per-frame peak brightness. Each event is padded so the faint tails are kept.
    Returns a list of (start_s, end_s). Use manual windows if this misses a faint pass.
    """
    peak = spec.bright.max(axis=0)
    n = max(1, int(round(smooth_s / spec.hop)))
    sm = uniform_filter1d(peak, n)
    # noise floor from the quieter 40 percent of frames, so long events don't inflate it
    lower = sm[sm <= np.percentile(sm, 40)]
    med = np.median(lower)
    mad = np.median(np.abs(lower - med)) * 1.4826 + 1e-9
    on = sm > med + k_mad * mad
    events, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = spec.t[i]
        if not v and start is not None:
            events.append([start, spec.t[i - 1]])
            start = None
    if start is not None:
        events.append([start, spec.t[-1]])
    merged = []
    for e in events:
        if merged and e[0] - merged[-1][1] < merge_gap_s:
            merged[-1][1] = e[1]
        else:
            merged.append(e)
    out = []
    for a, b in merged:
        if b - a >= min_dur_s:
            out.append((max(spec.t[0], a - pad_s), min(spec.t[-1], b + pad_s)))
    return out


def tolerant_brightness(spec: Spectrogram, bins: int = 1):
    """Brightness max-filtered across +/- bins, so a curve a hair off still scores."""
    return maximum_filter1d(spec.bright, 2 * bins + 1, axis=0)
