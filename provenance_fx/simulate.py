"""Synthetic but physically consistent test scene.

Builds: a terrain DEM, a few hours of air traffic (jets, props, airport traffic),
ADS-B observations of that traffic (sampled, noisy, quantised), a hidden listener,
and a security-camera-style audio clip containing two faint propeller flyovers
separated by about 920 seconds, rendered with emission-time Doppler and 1/r loss.
The pipeline never sees the hidden truth; tests compare against it afterwards.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.io import wavfile

from .adsb import Track, write_csv
from .geo import DEM, LocalFrame
from .physics import C_DEFAULT, heard_frequency

PROP_TYPES = ["C172", "C182", "PA28", "P28A", "SR22", "BE36", "C208", "BE20", "PC12", "DHC6", "AT76", ""]
JET_TYPES_SIM = ["B738", "A320", "E175", "CRJ9", "C56X", "B39M", "A321", "CL30", ""]


@dataclass
class TruthFlight:
    flight_id: str
    icao24: str
    callsign: str
    typecode: str
    is_prop: bool
    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    f0: float = 0.0


class _DenseModel:
    """Exact (dense) truth trajectory used to render audio."""

    def __init__(self, f: TruthFlight):
        self.t0, self.t1 = f.t[0], f.t[-1]
        self.s = [CubicSpline(f.t, a) for a in (f.x, f.y, f.z)]
        self.d = [s.derivative() for s in self.s]

    def pos(self, t):
        return np.stack([s(np.clip(t, self.t0, self.t1)) for s in self.s], axis=-1)

    def vel(self, t):
        return np.stack([d(np.clip(t, self.t0, self.t1)) for d in self.d], axis=-1)


def make_dem(frame: LocalFrame, half_km: float, rng) -> DEM:
    pad = half_km * 1000 + 25000
    xs = np.arange(-pad, pad + 1, 400.0)
    lats, _ = frame.to_latlon(xs * 0, xs)   # vary y (north)
    _, lons = frame.to_latlon(xs, xs * 0)   # vary x (east)
    X, Y = np.meshgrid(xs, xs)  # rows = y (lat), cols = x (lon)
    elev = 260.0 + 0.0008 * X - 0.0005 * Y
    for _ in range(14):
        cx, cy = rng.uniform(-pad, pad, 2)
        s = rng.uniform(2500, 9000)
        h = rng.uniform(-60, 140)
        elev += h * np.exp(-((X - cx) ** 2 + (Y - cy) ** 2) / (2 * s * s))
    return DEM(lats, lons, elev)


def _fly(rng, t_start, x0, y0, heading, speed, z0, duration, dt_s=0.5, turn_sd=0.5,
         climb=0.0, is_prop=True):
    n = int(duration / dt_s)
    t = t_start + np.arange(n) * dt_s
    x = np.empty(n); y = np.empty(n); z = np.empty(n)
    h, v, alt = np.radians(heading), speed, z0
    rate, left = 0.0, 0.0
    vz = climb
    for i in range(n):
        if left <= 0:
            left = rng.uniform(15, 80)
            rate = np.radians(rng.normal(0, turn_sd)) if rng.random() < 0.6 else 0.0
            v = np.clip(v + rng.normal(0, 3 if is_prop else 6), 45 if is_prop else 110,
                        115 if is_prop else 260)
            if climb == 0.0:
                vz = rng.normal(0, 1.0) if rng.random() < 0.4 else 0.0
        left -= dt_s
        h += rate * dt_s
        alt += vz * dt_s
        x[i], y[i], z[i] = x0, y0, alt
        x0 += v * np.sin(h) * dt_s
        y0 += v * np.cos(h) * dt_s
    return t, x, y, z


def _random_through_flight(rng, k, t_lo, t_hi, half_m, ground):
    is_prop = rng.random() < 0.4
    ang = rng.uniform(0, 2 * np.pi)
    R = half_m + 15000
    x0, y0 = R * np.sin(ang), R * np.cos(ang)
    tx, ty = rng.uniform(-half_m * 0.8, half_m * 0.8, 2)
    heading = np.degrees(np.arctan2(tx - x0, ty - y0))
    speed = rng.uniform(55, 105) if is_prop else rng.uniform(140, 240)
    z0 = ground + (rng.uniform(500, 2600) if is_prop else rng.uniform(3500, 11500))
    dur = 2 * R / speed
    t, x, y, z = _fly(rng, rng.uniform(t_lo - dur / 2, t_hi), x0, y0, heading, speed, z0, dur,
                      turn_sd=0.4 if is_prop else 0.1, is_prop=is_prop)
    typ = rng.choice(PROP_TYPES if is_prop else JET_TYPES_SIM)
    return TruthFlight(f"sim{k:04d}", f"a{k:05x}", f"N{k:04d}" if is_prop else f"SIM{k:03d}",
                       str(typ), is_prop, t, x, y, z, f0=float(rng.uniform(70, 125)))


def _airport_flight(rng, k, t_lo, t_hi, apt_xy, apt_z):
    is_prop = rng.random() < 0.7
    speed = rng.uniform(50, 75) if is_prop else rng.uniform(80, 110)
    heading = rng.uniform(0, 360)
    dur = rng.uniform(500, 900)
    t, x, y, z = _fly(rng, rng.uniform(t_lo, t_hi), apt_xy[0], apt_xy[1], heading, speed,
                      apt_z + 20, dur, turn_sd=0.6, climb=rng.uniform(3, 6), is_prop=is_prop)
    z = np.minimum(z, apt_z + rng.uniform(800, 1800))
    if rng.random() < 0.5:  # arrival = time-reversed departure
        t = t[0] + (t[-1] - t)[::-1]
        x, y, z = x[::-1], y[::-1], z[::-1]
    typ = rng.choice(PROP_TYPES if is_prop else ["E175", "CRJ9", "C56X", "CL30"])
    return TruthFlight(f"apt{k:04d}", f"b{k:05x}", f"N{k:03d}A", str(typ), is_prop, t, x, y, z,
                       f0=float(rng.uniform(70, 125)))


def _place_target(rng, k, obs, t_cpa, ground, lateral):
    """A propeller flight that passes `lateral` metres from obs (horizontally) at t_cpa."""
    speed = rng.uniform(65, 100)
    heading = rng.uniform(0, 360)
    z0 = ground + rng.uniform(450, 1300)
    t, x, y, z = _fly(rng, 0.0, 0.0, 0.0, heading, speed, z0, 900, turn_sd=0.6, is_prop=True)
    i = len(t) // 2
    hx, hy = x[i + 1] - x[i], y[i + 1] - y[i]
    nrm = np.hypot(hx, hy)
    px, py = -hy / nrm, hx / nrm  # perpendicular unit vector
    sx = obs[0] + lateral * px - x[i]
    sy = obs[1] + lateral * py - y[i]
    t = t - t[i] + t_cpa
    typ = rng.choice(["C172", "PA28", "SR22", "C182", "BE36"])
    return TruthFlight(f"tgt{k}", f"c{k:05x}", f"N{k}TG", str(typ), True, t, x + sx, y + sy, z,
                       f0=float(rng.uniform(80, 120)))


def _observe(rng, f: TruthFlight, frame: LocalFrame, period=1.0, keep=0.75, pos_sd=4.0) -> Track:
    ts = np.arange(f.t[0], f.t[-1], period)
    ts = ts[rng.random(len(ts)) < keep]
    m = _DenseModel(f)
    p = m.pos(ts)
    x = p[:, 0] + rng.normal(0, pos_sd, len(ts))
    y = p[:, 1] + rng.normal(0, pos_sd, len(ts))
    z = np.round(p[:, 2] / 7.62) * 7.62  # 25 ft altitude quantisation
    lat, lon = frame.to_latlon(x, y)
    return Track(f.flight_id, f.icao24, f.callsign, f.typecode, ts, lat, lon, z)


def _pink(rng, n):
    X = np.fft.rfft(rng.normal(size=n))
    fr = np.fft.rfftfreq(n)
    X[1:] /= np.sqrt(fr[1:])
    X[0] = 0
    y = np.fft.irfft(X, n)
    return y / y.std()


def render_audio(flights, obs, t_start, dur, sr=4000, c=C_DEFAULT, rng=None, tone_ref=0.03,
                 noise_rms=0.08, max_range=9000.0):
    rng = rng or np.random.default_rng(0)
    n = int(dur * sr)
    ta = np.arange(n) / sr
    out = noise_rms * _pink(rng, n)
    out += 0.01 * np.sin(2 * np.pi * 60 * ta) + 0.006 * np.sin(2 * np.pi * 120 * ta)
    ctrl = np.arange(0, dur + 0.1, 0.1)
    for f in flights:
        if not f.is_prop:
            continue
        m = _DenseModel(f)
        t_rx = t_start + ctrl
        p = m.pos(t_rx)
        if np.min(np.linalg.norm(p - obs, axis=-1)) > max_range * 1.5:
            continue
        freq, r, te = heard_frequency(m, obs[None, :].repeat(len(ctrl), 0), t_rx, f.f0, c)
        alive = (te >= f.t[0]) & (te <= f.t[-1])
        amp = tone_ref * (1000.0 / r) * np.exp(-r / 6000.0) * alive
        fa = np.interp(ta, ctrl, freq)
        aa = np.interp(ta, ctrl, amp)
        phase = 2 * np.pi * np.cumsum(fa) / sr
        wob = 1 + 0.1 * np.sin(2 * np.pi * 0.7 * ta + rng.uniform(0, 6))
        for h, g in ((1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15)):
            out += aa * wob * g * np.sin(h * phase + rng.uniform(0, 6))
    return out


def build_scene(out_dir: str, seed: int = 7, center=(40.30, -82.70), half_km=30.0,
                date="2026-09-08", hours=(13.0, 19.0), n_through=380, n_airport=120,
                delta_s=920.0, c=C_DEFAULT):
    rng = np.random.default_rng(seed)
    os.makedirs(out_dir, exist_ok=True)
    frame = LocalFrame(*center)
    dem = make_dem(frame, half_km, rng)
    day0 = dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc).timestamp()
    t_lo, t_hi = day0 + hours[0] * 3600, day0 + hours[1] * 3600
    half_m = half_km * 1000

    def ground(x, y):
        la, lo = frame.to_latlon(x, y)
        return float(dem.elevation(np.array(la), np.array(lo)))

    apt = np.array([-14000.0, 9000.0])
    apt_z = ground(*apt)

    # hidden listener: away from the airport and the region edge
    while True:
        o = rng.uniform(-half_m * 0.6, half_m * 0.6, 2)
        if np.hypot(*(o - apt)) > 10000:
            break
    obs_h = 3.0  # e.g. a camera on a pole
    obs = np.array([o[0], o[1], ground(*o) + obs_h])

    tA = rng.uniform(t_lo + 1800, t_hi - 1800 - delta_s)
    tB = tA + delta_s
    fl_a = _place_target(rng, 1, obs, tA, ground(*o), rng.uniform(150, 1200))
    fl_b = _place_target(rng, 2, obs, tB, ground(*o), rng.uniform(150, 1200))

    clip_start = tA - 150 - rng.uniform(0, 40)
    clip_end = tB + 150 + rng.uniform(0, 40)

    others = []
    k = 0
    while len(others) < n_through + n_airport:
        k += 1
        f = (_random_through_flight(rng, k, t_lo, t_hi, half_m, 260.0) if len(others) < n_through
             else _airport_flight(rng, k, t_lo, t_hi, apt, apt_z))
        # keep the clip quiet apart from the two targets (the silence is part of the signal)
        win = (f.t >= clip_start - 60) & (f.t <= clip_end + 30)
        if win.any():
            d = np.sqrt((f.x[win] - obs[0]) ** 2 + (f.y[win] - obs[1]) ** 2 + (f.z[win] - obs[2]) ** 2)
            if d.min() < 7000:
                continue
        others.append(f)
    flights = others + [fl_a, fl_b]
    rng.shuffle(flights)

    tracks = [_observe(rng, f, frame) for f in flights]
    write_csv(os.path.join(out_dir, "adsb.csv"), tracks)
    dem.save(os.path.join(out_dir, "dem.npz"))

    sr = 4000
    audio = render_audio(flights, obs, clip_start, clip_end - clip_start, sr=sr, c=c, rng=rng)
    audio = audio / np.max(np.abs(audio)) * 0.9
    wavfile.write(os.path.join(out_dir, "recording.wav"), sr, (audio * 32767).astype(np.int16))

    # short one-minute clip around event A, with a known start time (video's second test)
    s1 = tA + float(np.linalg.norm(fl_a_pos(fl_a, tA) - obs)) / c - 30
    i0 = int((s1 - clip_start) * sr)
    short = audio[i0:i0 + 60 * sr]
    wavfile.write(os.path.join(out_dir, "one_minute.wav"), sr, (short * 32767).astype(np.int16))

    olat, olon = frame.to_latlon(obs[0], obs[1])
    truth = {
        "observer_lat": float(olat), "observer_lon": float(olon),
        "observer_ground_m": float(obs[2] - obs_h), "observer_height_m": obs_h,
        "clip_start_unix": clip_start, "clip_duration_s": clip_end - clip_start,
        "one_minute_start_unix": s1,
        "event_a": {"flight_id": fl_a.flight_id, "cpa_emit_unix": tA, "f0": fl_a.f0},
        "event_b": {"flight_id": fl_b.flight_id, "cpa_emit_unix": tB, "f0": fl_b.f0},
        "speed_of_sound": c,
    }
    scenario = {
        "note": "What the analyst is allowed to know.",
        "date": date,
        "search_window_unix": [t_lo, t_hi],
        "bbox": _bbox(frame, half_m),
        "one_minute_start_unix": s1,
    }
    json.dump(truth, open(os.path.join(out_dir, "truth_HIDDEN.json"), "w"), indent=2)
    json.dump(scenario, open(os.path.join(out_dir, "scenario.json"), "w"), indent=2)
    return truth, scenario


def fl_a_pos(f, t):
    return _DenseModel(f).pos(np.array([t]))[0]


def _bbox(frame, half_m):
    la0, lo0 = frame.to_latlon(-half_m, -half_m)
    la1, lo1 = frame.to_latlon(half_m, half_m)
    return [float(la0), float(la1), float(lo0), float(lo1)]
