"""Synthetic ENF test clips: real or random grid drift -> hum harmonics + noise."""
from __future__ import annotations

import numpy as np


def random_grid(seconds, nominal=50, seed=0, sigma_mhz=25.0, tau_s=120.0):
    """Ornstein-Uhlenbeck-like 1 s frequency series around nominal (Hz)."""
    rng = np.random.default_rng(seed)
    n = int(seconds)
    a = np.exp(-1.0 / tau_s)
    x = np.zeros(n)
    s = sigma_mhz / 1000 * np.sqrt(1 - a * a)
    for i in range(1, n):
        x[i] = a * x[i - 1] + rng.normal(0, s)
    x += np.convolve(rng.normal(0, 0.0008, n), np.ones(5) / 5, "same")
    return nominal + x


def hum_audio(f1s, sr=8000, harmonics=((1, 0.02), (2, 0.01), (3, 0.006)), noise=0.05, seed=1,
              clock_ppm=0.0):
    """Audio whose hum follows f1s (Hz per second). harmonics: (k, amplitude)."""
    rng = np.random.default_rng(seed)
    n = int(len(f1s) * sr)
    t = np.arange(n) / sr
    f = np.interp(t, np.arange(len(f1s)), f1s) * (1 + clock_ppm * 1e-6)
    phase = 2 * np.pi * np.cumsum(f) / sr
    x = sum(a * np.sin(k * phase + rng.uniform(0, 6.28)) for k, a in harmonics)
    x = x + noise * rng.normal(0, 1, n)
    return sr, x.astype(np.float64)


PROFILES = {
    # name: (harmonic weights k -> relative amplitude); mimic common capture paths
    "near_mains": {1: 1.0, 2: 0.3, 3: 0.5, 5: 0.2},
    "phone_highpass": {2: 0.4, 3: 1.0, 4: 0.3, 5: 0.6, 6: 0.2, 7: 0.3},
    "camera_buzz": {2: 1.0, 4: 0.5, 6: 0.3},
    "odd_harmonics": {1: 0.3, 3: 1.0, 5: 0.7, 7: 0.4},
}


def mic_chain(f1s, rng, sr=1000, snr_db=None, profile=None, clock_ppm=None, stall=None, interferer=None, nominal=None):
    """Simulated real-world capture of a grid frequency series (Hz per second).

    Defaults were set so the extracted traces span the quality seen on real recordings
    (r against the true grid from ~0.3 to ~0.99). Random harmonic profile, hum SNR, recorder clock error and slow clock wander,
    white + 1/f noise, loud bursts and level changes, and optional stream stalls
    (chunks of audio silently removed, which breaks the timeline like a live stream does).
    Returns (sr, x, params).
    """
    n_s = len(f1s)
    profile = profile or rng.choice(list(PROFILES))
    snr_db = float(rng.uniform(-22, 10)) if snr_db is None else snr_db
    clock_ppm = float(rng.uniform(-100, 100)) if clock_ppm is None else clock_ppm
    stall = bool(rng.random() < 0.15) if stall is None else stall
    n = int(n_s * sr)
    t = np.arange(n) / sr
    wander = 2e-6 * np.sin(2 * np.pi * t / rng.uniform(600, 3000) + rng.uniform(0, 6.3))
    f = np.interp(t, np.arange(n_s), f1s) * (1 + clock_ppm * 1e-6 + wander)
    phase = 2 * np.pi * np.cumsum(f) / sr
    x = np.zeros(n)
    for k, w in PROFILES[profile].items():
        if k * 50 * 1.0 > sr / 2 * 0.9:
            continue
        a = w * 10 ** rng.uniform(-0.3, 0.3)
        x += a * np.sin(k * phase + rng.uniform(0, 6.28))
    # noise level so the strongest harmonic has `snr_db` in an 8 s STFT bin (0.125 Hz)
    sigma = np.sqrt((0.5 / 0.125) * (sr / 2) / 10 ** (snr_db / 10)) / np.sqrt(sr / 2)
    white = rng.normal(0, sigma, n)
    pink = np.cumsum(rng.normal(0, sigma * 0.05, n))
    pink -= np.convolve(pink, np.ones(sr) / sr, "same")
    x = x + white + pink
    # a steady non-mains tone near one hum harmonic (fans, inverters, crystal-locked buzz)
    interferer = bool(rng.random() < 0.25) if interferer is None else interferer
    if interferer:
        nominal = nominal or (60 if np.nanmean(f1s) > 55 else 50)
        k = int(rng.choice(list(PROFILES[profile])))
        fi = k * nominal + rng.uniform(-0.15, 0.15)
        x += rng.uniform(0.2, 1.0) * np.sin(2 * np.pi * fi * t + rng.uniform(0, 6.3))
    # level changes (people, volume) and short loud bursts
    env = np.interp(t, np.linspace(0, t[-1], 12), 10 ** rng.uniform(-0.3, 0.3, 12))
    x *= env
    for _ in range(rng.integers(0, 6)):
        i = rng.integers(0, max(1, n - 3 * sr))
        L = int(rng.uniform(0.3, 3) * sr)
        x[i:i + L] += rng.normal(0, sigma * rng.uniform(5, 30), len(x[i:i + L]))
    if stall:
        for _ in range(rng.integers(1, 4)):
            i = rng.integers(sr * 60, max(sr * 61, n - sr * 60))
            L = int(rng.uniform(3, 20) * sr)
            x = np.concatenate([x[:i], x[i + L:]])
    return sr, x, dict(profile=str(profile), snr_db=round(snr_db, 1), clock_ppm=round(clock_ppm, 1), stall=stall,
                       interferer=interferer)
