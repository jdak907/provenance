"""Synthetic test videos for light-flicker ENF: a lamp-lit room filmed by a rolling- or global-shutter camera.

SIMULATED, not real. The picture is rendered frame by frame:
- a static textured scene (walls, furniture, fine texture) lit by daylight (steady) plus a mains lamp;
- the lamp's light flickers at twice the grid frequency, following a REAL grid log (1 s values),
  with phase integrated from that frequency;
- each sensor row is sampled at its own time (rolling shutter: frame start + row / rows * read-out time;
  global shutter: read-out 0), and the exposure integrates the flicker (amplitude * sinc, phase shift);
- sensor noise, 8-bit rounding, optional camera pans, small hand-held jitter and auto-exposure steps;
- then H.264 (libx264) at a chosen CRF, with an optional AAC audio track made by the audio mic simulator.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from fractions import Fraction

import numpy as np
from scipy.io import wavfile


def _scene(H, W, pad, rng):
    """Reflectance, daylight and lamp maps on a padded canvas (H + 2 pad, W + 2 pad)."""
    h, w = H + 2 * pad, W + 2 * pad
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    refl = 0.55 + 0.15 * np.sin(x / w * rng.uniform(2, 5) + rng.uniform(0, 6)) * np.cos(y / h * rng.uniform(1, 3))
    for _ in range(rng.integers(6, 14)):            # furniture, frames, shelves
        y0, x0 = rng.integers(0, h - 20), rng.integers(0, w - 20)
        hh, ww = rng.integers(15, h // 2), rng.integers(15, w // 3)
        refl[y0:y0 + hh, x0:x0 + ww] = rng.uniform(0.15, 0.9)
    from scipy.ndimage import gaussian_filter
    tex = gaussian_filter(rng.normal(0, 1, (h, w)).astype(np.float32), 1.2)
    refl = np.clip(refl * (1 + 0.08 * tex / (tex.std() + 1e-9)), 0.05, 0.95)
    ly, lx = rng.uniform(0.1, 0.9) * h, rng.uniform(0.1, 0.9) * w
    lamp = 1.0 / (1 + ((x - lx) ** 2 + (y - ly) ** 2) / (rng.uniform(0.3, 0.8) * max(h, w)) ** 2)
    day = np.clip(1.0 - x / w * rng.uniform(0.3, 1.0), 0.1, 1.0) if rng.random() < 0.5 else np.ones_like(x) * 0.6
    return refl, day.astype(np.float32), lamp.astype(np.float32)


def render_video(out_path, f_grid_1s, fps="30000/1001", seconds=None, H=360, W=640, readout_ms=25.0,
                 exposure_s=1 / 250, mod_depth=0.03, lamp_share=0.7, crf=23, pans=0, jitter_px=0.0,
                 exposure_steps=0, noise=1.5, audio_f_1s=None, audio_snr_db=None, seed=0, flicker=True, gop=None, creation_time=None,
                 fixed_flicker_hz=None, preset="veryfast"):
    """Write an H.264 mp4. f_grid_1s: grid frequency (Hz) per second from the clip start.
    readout_ms=0 means a global shutter. fixed_flicker_hz: a lamp on an inverter (flicker not from the grid).
    Returns the parameters used (truth)."""
    rng = np.random.default_rng(seed)
    fr = Fraction(fps) if isinstance(fps, str) else Fraction(fps).limit_denominator(1001)
    fpsf = float(fr)
    seconds = seconds or (len(f_grid_1s) - 1)
    n = int(np.floor(seconds * fpsf))
    pad = 24
    refl, day, lamp = _scene(H, W, pad, rng)
    nominal = 60 if np.nanmean(f_grid_1s) > 55 else 50
    # flicker phase: 2 * integral of grid frequency, on a 1 kHz grid
    tt = np.arange(0, seconds + 1, 0.001)
    fg = np.interp(tt, np.arange(len(f_grid_1s)), np.nan_to_num(f_grid_1s, nan=nominal))
    if fixed_flicker_hz:
        fg = np.full_like(tt, fixed_flicker_hz / 2.0)
    phi = 2 * np.pi * 2 * np.cumsum(fg) * 0.001 + rng.uniform(0, 2 * np.pi)
    f_fl = 2.0 * nominal
    amp = mod_depth * np.sinc(f_fl * exposure_s) if flicker else 0.0
    # camera path: pans (smooth moves of 10-40 px over 1-3 s) and hand-held jitter
    dx = np.zeros(n); dy = np.zeros(n)
    pan_log = []
    for _ in range(pans):
        a = int(rng.uniform(0.1, 0.9) * n); L = int(rng.uniform(1, 3) * fpsf)
        tx, ty = rng.uniform(-pad + 4, pad - 4), rng.uniform(-pad / 2, pad / 2)
        ramp = np.clip((np.arange(n) - a) / max(L, 1), 0, 1)
        dx += tx * ramp; dy += ty * ramp
        pan_log.append(dict(t_s=round(a / fpsf, 1), dur_s=round(L / fpsf, 1)))
    if jitter_px:
        from scipy.ndimage import gaussian_filter1d
        dx += gaussian_filter1d(rng.normal(0, 1, n), fpsf / 2) * jitter_px * np.sqrt(fpsf)
        dy += gaussian_filter1d(rng.normal(0, 1, n), fpsf / 2) * jitter_px * np.sqrt(fpsf)
    dx = np.clip(dx, -pad + 1, pad - 1); dy = np.clip(dy, -pad + 1, pad - 1)
    gain = np.ones(n)
    steps = []
    for _ in range(exposure_steps):
        a = int(rng.uniform(0.1, 0.9) * n); g = rng.uniform(0.8, 1.25)
        gain *= np.where(np.arange(n) >= a, g, 1.0) ** np.clip((np.arange(n) - a) / (0.3 * fpsf), 0, 1)
        steps.append(dict(t_s=round(a / fpsf, 1), gain=round(g, 3)))
    level = rng.uniform(0.45, 0.75)
    row_t = (np.arange(H) + 0.5) / H * (readout_ms / 1000.0)
    tmpdir = tempfile.mkdtemp(prefix="vsim_")
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}",
           "-r", f"{fr.numerator}/{fr.denominator}", "-i", "pipe:0"]
    ap = None
    if audio_f_1s is not None:
        from .simulate import mic_chain
        sr, xa, apar = mic_chain(np.asarray(audio_f_1s, float), rng, sr=8000, snr_db=audio_snr_db, stall=False,
                                 interferer=False)
        xa = xa[: int(seconds * sr)]
        xa = 0.3 * xa / (np.max(np.abs(xa)) + 1e-9)
        ap = os.path.join(tmpdir, "a.wav")
        wavfile.write(ap, sr, (xa * 32767).astype(np.int16))
        cmd += ["-i", ap]
    cmd += ["-map", "0:v"] + (["-map", "1:a", "-c:a", "aac", "-b:a", "96k"] if ap else []) + \
           ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"] + \
           (["-g", str(int(gop))] if gop else []) + \
           (["-metadata", "creation_time=" + _iso(creation_time)] if creation_time is not None else []) + \
           ["-movflags", "+faststart", out_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for k in range(n):
            t0 = k / fpsf
            ts = t0 + row_t + exposure_s / 2
            ph = np.interp(ts, tt, phi)
            fl = 1.0 + amp * np.cos(ph)                               # (H,)
            ox, oy = int(round(pad + dx[k])), int(round(pad + dy[k]))
            R = refl[oy:oy + H, ox:ox + W]; D = day[oy:oy + H, ox:ox + W]; Lm = lamp[oy:oy + H, ox:ox + W]
            light = (1 - lamp_share) * D + lamp_share * Lm * fl[:, None]
            img = level * gain[k] * R * light
            img = img + rng.normal(0, 1, img.shape).astype(np.float32) * (noise / 255.0) * np.sqrt(0.3 + img)
            p.stdin.write(np.clip(np.round(img * 255), 0, 255).astype(np.uint8).tobytes())
        p.stdin.close()
        err = p.stderr.read().decode(errors="replace")
        if p.wait() != 0:
            raise RuntimeError("ffmpeg encode failed: " + err[-300:])
    finally:
        if ap and os.path.exists(ap):
            os.unlink(ap)
        os.rmdir(tmpdir) if os.path.isdir(tmpdir) and not os.listdir(tmpdir) else None
    return dict(fps=f"{fr.numerator}/{fr.denominator}", seconds=seconds, H=H, W=W, readout_ms=readout_ms,
                exposure_s=exposure_s, mod_depth=mod_depth, effective_depth=round(float(amp), 5), lamp_share=lamp_share,
                crf=crf, pans=pan_log, jitter_px=jitter_px, exposure_steps=steps, noise=noise, flicker=flicker,
                fixed_flicker_hz=fixed_flicker_hz, nominal=nominal, audio=audio_f_1s is not None, seed=seed,
                gop=gop, creation_time=creation_time)


def _iso(t):
    import datetime as _dt
    return _dt.datetime.fromtimestamp(float(t), _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
