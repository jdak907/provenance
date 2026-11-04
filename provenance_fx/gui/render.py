"""Spectrogram images and result payloads for the GUI."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

HACKER = LinearSegmentedColormap.from_list(
    "hacker", ["#030605", "#04140d", "#06331f", "#0b6b3f", "#19c37d", "#7dffc4", "#eafff6"])


def _pool_max(A, h, w):
    """Downsample a (F,T) array to at most (h,w) by max-pooling (keeps thin curves visible)."""
    F, T = A.shape
    sf = max(1, int(np.ceil(F / h)))
    st = max(1, int(np.ceil(T / w)))
    F2, T2 = F // sf * sf, T // st * st
    if F2 == 0 or T2 == 0:
        return A
    B = A[:F2, :T2].reshape(F2 // sf, sf, T2 // st, st).max(axis=(1, 3))
    return B


def spec_png(spec, t0, t1, f0, f1, w=1200, h=420, mode="bright", vmax=None):
    from matplotlib import pyplot as plt

    tm = (spec.t >= t0) & (spec.t <= t1)
    fm = (spec.f >= f0) & (spec.f <= f1)
    if tm.sum() < 2 or fm.sum() < 2:
        A = np.zeros((2, 2))
    else:
        A = (spec.bright if mode == "bright" else spec.db)[np.ix_(fm, tm)]
    A = _pool_max(A, h, w)
    if mode == "bright":
        lo, hi = 0.0, vmax or 6.0
    else:
        lo, hi = np.percentile(A, 5), np.percentile(A, 99.7)
    img = np.clip((A - lo) / max(hi - lo, 1e-9), 0, 1)[::-1]  # low frequency at the bottom
    buf = io.BytesIO()
    plt.imsave(buf, img, cmap=HACKER, format="png")
    return buf.getvalue()


def thin(t, f, n=600):
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    if len(t) > n:
        i = np.linspace(0, len(t) - 1, n).astype(int)
        t, f = t[i], f[i]
    ok = np.isfinite(f)
    return [[round(float(a), 2), round(float(b), 2)] for a, b in zip(t[ok], f[ok])]
