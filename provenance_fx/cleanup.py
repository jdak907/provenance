"""Audio clean-up used by the GUI (and usable from Python).

Steps, in order: trim, high-pass, low-pass, steady-tone removal and noise reduction
(both by spectral subtraction against a running per-frequency floor), then gain.
Output is mono at `out_sr` (default 4000 Hz, enough for the 30 to 400 Hz analysis band).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import signal

from .spectro import steady_floor


@dataclass
class CleanSettings:
    trim_start: float = 0.0          # seconds
    trim_end: float | None = None    # seconds, None = to the end
    highpass_hz: float = 0.0         # 0 = off
    lowpass_hz: float = 0.0          # 0 = off
    remove_steady: bool = True       # subtract hums and lines that stay put
    denoise: float = 0.0             # 0 to 1, extra broadband noise reduction
    gain_db: float = 0.0

    def to_dict(self):
        return asdict(self)


def resample(x, sr, out_sr):
    if sr == out_sr:
        return x
    g = np.gcd(int(sr), int(out_sr))
    return signal.resample_poly(x, out_sr // g, sr // g)


def clean(x, sr, st: CleanSettings, out_sr: int = 4000):
    x = resample(np.asarray(x, dtype=np.float64), sr, out_sr)
    sr = out_sr
    a = int(max(0.0, st.trim_start) * sr)
    b = int(st.trim_end * sr) if st.trim_end else len(x)
    x = x[a:max(a + sr, b)]
    if st.highpass_hz and st.highpass_hz > 0:
        x = signal.sosfiltfilt(signal.butter(4, st.highpass_hz, "highpass", fs=sr, output="sos"), x)
    if st.lowpass_hz and 0 < st.lowpass_hz < sr / 2:
        x = signal.sosfiltfilt(signal.butter(4, st.lowpass_hz, "lowpass", fs=sr, output="sos"), x)
    strength = (1.0 if st.remove_steady else 0.0) + 1.5 * float(st.denoise)
    if strength > 0:
        nper = sr  # 1 s window, 0.25 s hop: same resolution as the analysis
        hop = sr // 4
        f, t, Z = signal.stft(x, fs=sr, nperseg=nper, noverlap=nper - hop)
        Z = Z.astype(np.complex64)
        M = np.abs(Z) + 1e-12
        if st.remove_steady:
            floor = 10 ** (steady_floor(20 * np.log10(M), 0.25, 60.0) / 20)
        else:
            floor = np.median(M, axis=1, keepdims=True)
        G = np.clip(1.0 - strength * floor / M, 0.05, 1.0)
        _, x = signal.istft(Z * G, fs=sr, nperseg=nper, noverlap=nper - hop)
    x = x * 10 ** (st.gain_db / 20)
    peak = np.max(np.abs(x)) or 1.0
    if peak > 1.0:
        x = x / peak
    return x.astype(np.float32), sr
