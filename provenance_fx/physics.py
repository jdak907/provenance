"""Doppler physics for a moving sound source and a fixed listener.

Key idea from the video: the pitch heard at reception time t_rx depends on the
aircraft's radial velocity at the EMISSION time t_e, where
    t_rx = t_e + |p(t_e) - observer| / c.
Using the radial velocity at t_rx instead (the "naive" model) gives a wrong curve,
not just a delayed one.
"""
from __future__ import annotations

import numpy as np

C_DEFAULT = 343.0  # m/s, dry air near 20 C


def speed_of_sound(temp_c: float = 20.0) -> float:
    return 331.3 * np.sqrt(1.0 + temp_c / 273.15)


def doppler(f0, v_radial, c=C_DEFAULT):
    """Moving source, still listener. v_radial > 0 means moving away."""
    return f0 * c / (c + v_radial)


def emission_times(model, obs, t_rx, c=C_DEFAULT, iters: int = 8):
    """Solve t_e + |p(t_e) - obs| / c = t_rx by fixed-point iteration.

    obs: (..., 3) observer positions; t_rx: array broadcastable to obs[..., 0].
    Converges because aircraft speed is far below the speed of sound.
    """
    t_rx = np.asarray(t_rx, dtype=float)
    te = t_rx.copy()
    for _ in range(iters):
        p = model.pos(te)
        r = np.linalg.norm(p - obs, axis=-1)
        te = t_rx - r / c
    return te


def heard_frequency(model, obs, t_rx, f0, c=C_DEFAULT):
    """Correct (emission-time) Doppler curve. Returns (freq, slant_range, t_emit)."""
    te = emission_times(model, obs, t_rx, c)
    p = model.pos(te)
    v = model.vel(te)
    d = p - obs
    r = np.linalg.norm(d, axis=-1)
    vr = np.sum(v * d, axis=-1) / r
    return doppler(f0, vr, c), r, te


def naive_frequency(model, obs, t_rx, f0, c=C_DEFAULT):
    """The WRONG model the video warns about: radial velocity at the reception time."""
    p = model.pos(t_rx)
    v = model.vel(t_rx)
    d = p - obs
    r = np.linalg.norm(d, axis=-1)
    vr = np.sum(v * d, axis=-1) / r
    return doppler(f0, vr, c)


def straight_line_curve(t_rx, f0, v, d, t_cpa_rx, c=C_DEFAULT):
    """Closed-form heard pitch for a straight, constant-speed pass.

    v: speed (m/s). d: closest slant distance (m). t_cpa_rx: time the closest
    point is HEARD (the 'delayed CPA time'). Includes propagation delay exactly.
    Only two shape parameters matter: v sets the size of the drop, d sets how fast it happens.
    """
    t_rx = np.asarray(t_rx, dtype=float)
    v = min(abs(v), 0.95 * c)
    d = max(abs(d), 1.0)
    te0 = t_cpa_rx - d / c  # emission time of the closest point
    T = t_rx - te0
    a = c * c - v * v
    disc = v * v * c * c * T * T + a * d * d
    u = (c * c * T - np.sqrt(disc)) / a  # emission time relative to te0
    vr = v * v * u / np.sqrt(v * v * u * u + d * d)
    return doppler(f0, vr, c)


def straight_line_extremes(f0, v, c=C_DEFAULT):
    """Approach (high) and departure (low) pitch."""
    return f0 * c / (c - v), f0 * c / (c + v)
