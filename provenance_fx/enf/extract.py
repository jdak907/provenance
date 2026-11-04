"""Hum check, 50/60 Hz guess and multi-harmonic ENF extraction.

Method (see enf_research.md):
  * down-sample to 1 kHz, keep harmonics 1..7 below 450 Hz
  * STFT, 8 s Hann frames, 1 s hop, 4x zero padding, per-harmonic band
  * per-harmonic local SNR (peak over the band's noise ring)
  * harmonic selection by mutual correlation with the strongest harmonic (Hua 2021)
  * SNR-weighted spectrum combining on a common deviation axis (Hajj-Ahmad 2013)
  * dynamic-programming ridge tracking, then quadratic (QIFFT) peak interpolation
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal

WORK_SR = 1000
MAX_HARMONIC_HZ = 450.0


def work_rate(sr):
    """1 kHz working rate, or the native rate for low-rate mains references (e.g. 400 Hz)."""
    return int(sr) if sr < WORK_SR else WORK_SR


def downsample(x, sr, work_sr=WORK_SR):
    x = np.asarray(x, dtype=np.float64)
    x = x - np.mean(x)
    work_sr = min(work_sr, work_rate(sr))
    if sr == work_sr:
        return x
    g = np.gcd(int(sr), int(work_sr))
    return signal.resample_poly(x, work_sr // g, int(sr) // g)


def _harmonics(nominal, kmax=7, fs=WORK_SR):
    top = min(MAX_HARMONIC_HZ, fs / 2 - 15)
    return [k for k in range(1, kmax + 1) if k * nominal <= top]


def hum_scan(x, sr, already_down=False) -> dict:
    """Quick look: SNR (dB) of a narrow line at each 50 and 60 Hz harmonic, and a 50/60 guess.

    Frequencies shared by both families (300, 600 Hz ...) are ignored for the guess.
    """
    xd = x if already_down else downsample(x, sr)
    fs = work_rate(sr)
    nper = min(len(xd), fs * 16)
    f, P = signal.welch(xd, fs, nperseg=nper, noverlap=nper // 2)
    out = {}
    for nom in (50, 60):
        rows = []
        for k in _harmonics(nom, fs=fs):
            fc = nom * k
            bw = 0.25 * k + 0.3
            band = (f >= fc - bw) & (f <= fc + bw)
            ring = ((f > fc - bw - 3) & (f < fc - bw - 0.5)) | ((f > fc + bw + 0.5) & (f < fc + bw + 3))
            if not band.any() or not ring.any():
                continue
            noise = np.median(P[ring]) + 1e-30
            pk = P[band].max()
            rows.append(dict(k=k, hz=fc, snr_db=float(10 * np.log10((pk + 1e-30) / noise)),
                             peak_hz=float(f[band][np.argmax(P[band])]), shared=(fc % 300 == 0)))
        out[nom] = rows

    def score(rows):
        v = sorted([r["snr_db"] for r in rows if not r["shared"]], reverse=True)[:3]
        return float(np.mean(v)) if v else 0.0

    s50, s60 = score(out[50]), score(out[60])
    best = 50 if s50 >= s60 else 60
    top = max([r["snr_db"] for r in out[best] if not r["shared"]] or [0])
    nominal = best if (top >= 6.0 and abs(s50 - s60) >= 1.5) else None
    return dict(nominal=nominal, guess=best, score50=s50, score60=s60, max_snr_db=float(top),
                lines50=out[50], lines60=out[60],
                note=("clear %d Hz hum family" % best) if nominal else
                     ("no clear mains hum line (best %d Hz family, %.1f dB)" % (best, top)))


@dataclass
class EnfTrace:
    t: np.ndarray                 # frame centre, seconds from start of file
    f: np.ndarray                 # ENF estimate, Hz at the fundamental (NaN where unreliable)
    snr_db: np.ndarray            # combined per-frame SNR
    nominal: int
    harmonics_used: list
    harmonic_snr_db: dict         # k -> median SNR
    harmonic_corr: dict           # k -> correlation with the anchor harmonic
    per_harmonic: dict = field(default_factory=dict)   # k -> trace (fundamental units)
    frame_s: float = 8.0
    hop_s: float = 1.0

    @property
    def duration(self):
        return float(self.t[-1] - self.t[0] + self.hop_s) if len(self.t) else 0.0

    def valid_fraction(self):
        return float(np.mean(np.isfinite(self.f))) if len(self.f) else 0.0

    def to_dict(self, max_points=None):
        t, f, s = self.t, self.f, self.snr_db
        if max_points and len(t) > max_points:
            idx = np.linspace(0, len(t) - 1, max_points).astype(int)
            t, f, s = t[idx], f[idx], s[idx]
        nan = lambda a: [None if not np.isfinite(v) else round(float(v), 5) for v in a]
        return dict(t=[round(float(v), 2) for v in t], f=nan(f), snr_db=nan(s), nominal=self.nominal,
                    harmonics_used=self.harmonics_used,
                    harmonic_snr_db={str(k): round(v, 2) for k, v in self.harmonic_snr_db.items()},
                    harmonic_corr={str(k): (None if not np.isfinite(v) else round(v, 3))
                                   for k, v in self.harmonic_corr.items()},
                    frame_s=self.frame_s, hop_s=self.hop_s)


def _band_spectrogram(xd, fs, bands, frame_s, hop_s, pad=4, chunk=256):
    n = int(frame_s * fs)
    hop = int(hop_s * fs)
    nfft = int(2 ** np.ceil(np.log2(n * pad)))
    freqs = np.fft.rfftfreq(nfft, 1 / fs)
    win = signal.windows.hann(n, sym=False)
    if len(xd) < n:
        raise ValueError(f"recording too short for ENF ({len(xd) / fs:.1f} s, need at least {frame_s:.0f} s)")
    n_frames = 1 + (len(xd) - n) // hop
    idx = [np.where((freqs >= lo) & (freqs <= hi))[0] for lo, hi in bands]
    outs = [np.empty((len(i), n_frames)) for i in idx]
    for c0 in range(0, n_frames, chunk):
        c1 = min(n_frames, c0 + chunk)
        starts = np.arange(c0, c1) * hop
        frames = np.stack([xd[s:s + n] for s in starts]) * win
        spec = np.fft.rfft(frames, nfft, axis=1)
        p = (spec.real ** 2 + spec.imag ** 2)
        for o, i in zip(outs, idx):
            o[:, c0:c1] = p[:, i].T
    t = (np.arange(n_frames) * hop + n / 2) / fs
    return t, [freqs[i] for i in idx], outs


def _qifft(logp, j):
    """Quadratic interpolation offset (in bins) around integer peak j for each column."""
    a = logp[np.clip(j - 1, 0, logp.shape[0] - 1), np.arange(logp.shape[1])]
    b = logp[j, np.arange(logp.shape[1])]
    c = logp[np.clip(j + 1, 0, logp.shape[0] - 1), np.arange(logp.shape[1])]
    den = a - 2 * b + c
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.where(np.abs(den) > 1e-12, 0.5 * (a - c) / den, 0.0)
    d[(j == 0) | (j == logp.shape[0] - 1)] = 0.0
    return np.clip(d, -0.5, 0.5)


def _dp_ridge(score, max_jump, penalty):
    """Viterbi path through score (S states x T frames), max_jump states per frame."""
    S, T = score.shape
    acc = score[:, 0].copy()
    back = np.zeros((S, T), dtype=np.int32)
    offs = np.arange(-max_jump, max_jump + 1)
    cost = penalty * (offs / max(max_jump, 1)) ** 2
    for t in range(1, T):
        best = np.full(S, -np.inf)
        arg = np.zeros(S, dtype=np.int32)
        for o, c in zip(offs, cost):
            src = np.arange(S) - o
            ok = (src >= 0) & (src < S)
            cand = np.full(S, -np.inf)
            cand[ok] = acc[src[ok]] - c
            better = cand > best
            best[better] = cand[better]
            arg[better] = src[better]
        acc = best + score[:, t]
        back[:, t] = arg
    path = np.zeros(T, dtype=np.int32)
    path[-1] = int(np.argmax(acc))
    for t in range(T - 1, 0, -1):
        path[t - 1] = back[path[t], t]
    return path


def extract_enf(x, sr, nominal=None, harmonics=None, frame_s=8.0, hop_s=1.0, max_dev=0.3,
                min_harmonic_snr_db=3.0, corr_keep=0.4, track="dp", log=None) -> EnfTrace:
    """Estimate the ENF trace from raw audio. Returns an EnfTrace (fundamental-frequency units)."""
    log = log or (lambda m: None)
    xd = downsample(x, sr)
    if not np.any(np.abs(xd) > 1e-9):
        raise ValueError("the audio track is digital silence: no hum to analyse")
    fs = work_rate(sr)
    if nominal is None:
        scan = hum_scan(xd, fs, already_down=True)
        nominal = scan["nominal"] or scan["guess"]
        log(f"hum scan: {scan['note']}; using {nominal} Hz")
    ks = harmonics or _harmonics(nominal, fs=fs)
    bands, rings = [], []
    for k in ks:
        bw = k * max_dev + 0.2
        bands.append((k * nominal - bw - 2.5, k * nominal + bw + 2.5))   # band plus noise ring
        rings.append(bw)
    t, fb, P = _band_spectrogram(xd, fs, bands, frame_s, hop_s)
    per, snr_k, snr_med, inband = {}, {}, {}, {}
    for k, f, p, bw in zip(ks, fb, P, rings):
        fc = k * nominal
        core = np.abs(f - fc) <= bw
        ring = (np.abs(f - fc) > bw + 0.5)
        noise = np.median(p[ring], axis=0) + 1e-30
        pc = p[core]
        j = np.argmax(pc, axis=0)
        lp = np.log(pc + 1e-30)
        d = _qifft(lp, j)
        df = f[1] - f[0]
        per[k] = (f[core][j] + d * df) / k
        # excess over what the largest of N noise bins would give (max/median of exponential noise)
        n_eff = max(2.0, core.sum() / 4.0)
        bias = 10 * np.log10((np.log(n_eff) + 0.5772) / np.log(2))
        s = 10 * np.log10((pc[j, np.arange(pc.shape[1])] + 1e-30) / noise) - bias
        snr_k[k] = s
        snr_med[k] = float(np.median(s))
        inband[k] = (f[core], pc / noise)
    good = [k for k in ks if snr_med[k] >= min_harmonic_snr_db] or [max(ks, key=lambda k: snr_med[k])]
    # higher harmonics give k-times finer resolution in fundamental units, so favour them a little
    anchor = max(good, key=lambda k: snr_med[k] + 10 * np.log10(k))
    corr = {}
    from scipy.ndimage import median_filter
    sm = {k: median_filter(per[k], size=9, mode="nearest") for k in ks}
    for k in ks:
        if k == anchor:
            corr[k] = 1.0
            continue
        a, b = sm[anchor], sm[k]
        corr[k] = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else float("nan")
    used = [k for k in good if k == anchor or (np.isfinite(corr[k]) and corr[k] >= corr_keep)]
    log(f"harmonic SNR (dB): " + ", ".join(f"{k}x={snr_med[k]:.1f}" for k in ks)
        + f"; anchor {anchor}x; used {used}")
    # spectrum combining on a common deviation grid (fundamental units)
    grid = np.arange(-max_dev, max_dev + 1e-9, 0.002)
    C = np.zeros((len(grid), len(t)))
    wsum = 0.0
    for k in used:
        f, r = inband[k]
        dev = f / k - nominal
        w = 10 ** (snr_med[k] / 10)
        for ti in range(0, len(t), 512):
            sl = slice(ti, min(len(t), ti + 512))
            blk = r[:, sl]
            # interpolate each column on to the common grid
            Ci = np.empty((len(grid), blk.shape[1]))
            for c in range(blk.shape[1]):
                Ci[:, c] = np.interp(grid, dev, blk[:, c])
            C[:, sl] += w * Ci
        wsum += w
    C /= wsum
    logC = np.log(C + 1e-12)
    sc = logC - np.median(logC, axis=0, keepdims=True)
    max_jump = max(1, int(round(0.03 * hop_s / 0.002)))
    path = _dp_ridge(sc, max_jump=max_jump, penalty=2.0) if track == "dp" else np.argmax(sc, axis=0)
    d = _qifft(logC, path)
    ridge = nominal + grid[path] + d * 0.002
    # refine: SNR- and k^2-weighted mean of per-harmonic QIFFT peaks that sit on the ridge
    num = np.zeros(len(t)); den = np.zeros(len(t))
    for k in used:
        near = np.abs(per[k] - ridge) <= 0.02
        w = (10 ** (np.clip(snr_k[k], -10, 40) / 10)) * k * k * near
        num += w * np.where(near, per[k], 0.0); den += w
    fhat = np.where(den > 0, num / np.maximum(den, 1e-30), ridge)
    # C is already in "times the local noise floor" units (each band divided by its noise ring)
    n_eff = max(2.0, (2 * max_dev) / (1.5 / frame_s))     # independent resolution cells on the grid
    bias = 10 * np.log10(np.log(n_eff) + 0.5772)
    comb_snr = 10 * np.log10(C[path, np.arange(len(t))] + 1e-30) - bias
    # reject frames hit by broadband bursts or with no line
    fhat = np.where(comb_snr >= 2.0, fhat, np.nan)
    fhat = despike(fhat)
    return EnfTrace(t=t, f=fhat, snr_db=comb_snr, nominal=int(nominal), harmonics_used=used,
                    harmonic_snr_db=snr_med, harmonic_corr=corr, per_harmonic=per,
                    frame_s=frame_s, hop_s=hop_s)


def despike(f, win=15, k=4.0, floor_hz=0.008):
    """Drop frames that jump away from the local median (wind, clicks, broadband bursts)."""
    from scipy.ndimage import median_filter
    f = np.asarray(f, float).copy()
    ok = np.isfinite(f)
    if ok.sum() < win:
        return f
    idx = np.arange(len(f))
    filled = np.interp(idx, idx[ok], f[ok])
    med = median_filter(filled, size=win, mode="nearest")
    res = np.abs(filled - med)
    mad = 1.4826 * np.median(res[ok]) + 1e-12
    f[ok & (res > max(k * mad, floor_hz))] = np.nan
    return f


def detect_enf(tr: EnfTrace, scan: dict | None = None) -> dict:
    """Is there a real mains ENF in this trace? Returns verdict present / weak / absent with reasons."""
    reasons, score = [], 0.0
    f = tr.f[np.isfinite(tr.f)]
    valid = tr.valid_fraction()
    snr = float(np.nanmedian(tr.snr_db)) if len(tr.snr_db) else 0.0
    best_h = max(tr.harmonic_snr_db.values()) if tr.harmonic_snr_db else 0.0
    others = [v for k, v in tr.harmonic_corr.items() if k in tr.harmonics_used and v < 0.999]
    agree = float(np.mean(others)) if others else float("nan")
    if len(f) < 30:
        return dict(verdict="absent", score=0.0, reasons=["too few usable frames"], snr_db=snr, flat=False,
                    agreement=agree, std_mhz=None, smooth=None, valid=valid)
    rstd = lambda a: 1.4826 * float(np.median(np.abs(a - np.median(a))))
    std = rstd(f) * 1000
    smooth = float(rstd(np.diff(f)) / (rstd(f) + 1e-12))
    # flatness on the cleanest harmonic: crystal-locked hum (inverter, UPS, synthetic tone) barely moves
    flat_k = None
    if tr.per_harmonic:
        kbest = max(tr.harmonic_snr_db, key=lambda k: tr.harmonic_snr_db[k] + 10 * np.log10(k))
        hk = tr.per_harmonic[kbest]
        flat_k = (kbest, rstd(hk) * 1000, float(np.median(hk)))
    if best_h >= 10:
        score += 0.35; reasons.append(f"strong hum line ({best_h:.1f} dB)")
    elif best_h >= 5:
        score += 0.2; reasons.append(f"moderate hum line ({best_h:.1f} dB)")
    else:
        reasons.append(f"weak or no hum line ({best_h:.1f} dB)")
    if np.isfinite(agree):
        if agree >= 0.7:
            score += 0.3; reasons.append(f"harmonics agree (mean r={agree:.2f}) -> real mains drift")
        elif agree >= 0.4:
            score += 0.15; reasons.append(f"harmonics partly agree (r={agree:.2f})")
        else:
            reasons.append(f"harmonics disagree (r={agree:.2f})")
    else:
        score += 0.1; reasons.append("only one usable harmonic (cannot cross-check)")
    flat = std < 1.5 or (flat_k is not None and tr.duration >= 240 and flat_k[1] < 2.0
                         and tr.harmonic_snr_db[flat_k[0]] >= 8)
    if flat:
        reasons.append(f"hum is nearly fixed in frequency (harmonic {flat_k[0] if flat_k else '?'}x moves only "
                       f"{(flat_k[1] if flat_k else std):.1f} mHz): likely crystal-locked (inverter, UPS, "
                       "synthetic tone), not the grid")
        score -= 0.35
    elif std > 60:
        reasons.append(f"trace wanders too much ({std:.0f} mHz): probably noise")
        score -= 0.2
    else:
        score += 0.1
    if smooth < 0.25:
        score += 0.2; reasons.append(f"smooth drift (diff/std={smooth:.2f})")
    elif smooth < 0.5:
        score += 0.1; reasons.append(f"somewhat noisy trace (diff/std={smooth:.2f})")
    else:
        reasons.append(f"jumpy trace (diff/std={smooth:.2f}) -> mostly noise")
    score += 0.05 * valid
    score = float(np.clip(score, 0, 1))
    verdict = "present" if score >= 0.65 else ("weak" if score >= 0.4 else "absent")
    return dict(verdict=verdict, score=round(score, 3), reasons=reasons, snr_db=round(snr, 2), flat=bool(flat),
                agreement=None if not np.isfinite(agree) else round(agree, 3), std_mhz=round(std, 2),
                smooth=round(smooth, 3), valid=round(valid, 3))
