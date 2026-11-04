"""Privacy audit: does this recording carry aircraft Doppler curves that could locate it?

Also reproduces the video's mitigation tests: a high-pass filter followed by
"boosting" (re-normalising) often brings the curve back, because the filter lowers
the noise floor by the same amount as the tone.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from . import measure, spectro


def scan(x, sr, fmin=30.0, fmax=400.0):
    spec = spectro.compute(x, sr, fmin=fmin, fmax=fmax)
    found = []
    for i, (a, b) in enumerate(spectro.detect_events(spec)):
        r = spectro.trace_ridge(spec, a, b, None, None)
        try:
            m = measure.fit_event(spec, a, b, f"curve{i + 1}", ridge=r)
        except Exception:
            continue
        drop = (m.f0 * 343 / (343 - m.speed)) - (m.f0 * 343 / (343 + m.speed))
        # speeds or distances pinned at the fit limits are not real flyovers
        if m.rms_hz < 0.12 * drop and 20 < m.speed < 290 and m.slant_cpa > 40:
            found.append(m)
    return spec, found


def highpass(x, sr, cutoff, order=4):
    sos = signal.butter(order, cutoff, "highpass", fs=sr, output="sos")
    y = signal.sosfiltfilt(sos, x)
    return y / (np.max(np.abs(y)) or 1.0)  # "boost all the frequencies"


def audit(path, test_highpass=None, out=print):
    sr, x = spectro.load_audio(path)
    _, found = scan(x, sr)
    lines = [f"Audio: {path} ({len(x) / sr:.0f} s at {sr} Hz)"]
    if not found:
        lines.append("No clear Doppler flyover curves found in 30 to 400 Hz. Exposure: LOW "
                     "(this does not prove none are present).")
    else:
        lines.append(f"Found {len(found)} Doppler flyover curve(s). Exposure: "
                     f"{'HIGH' if len(found) >= 2 else 'MEDIUM'}.")
        for m in found:
            lines.append(f"  {m.name}: heard closest approach at {m.t_cpa:.0f} s, about {m.speed:.0f} m/s, "
                         f"about {m.slant_cpa:.0f} m away, base pitch {m.f0:.0f} Hz")
        if len(found) >= 2:
            lines.append("  Two curves plus the gap between them is enough to search a whole country "
                         "if someone has the ADS-B history for that day.")
        lines.append("  One curve plus a known recording time (a phone call, a timestamped post) can be "
                     "enough on its own.")
    if test_highpass:
        y = highpass(x, sr, test_highpass)
        _, f2 = scan(y, sr)
        lines.append(f"After a 4th-order {test_highpass:.0f} Hz high-pass and re-boost: "
                     f"{len(f2)} curve(s) still detectable."
                     + ("  The filter did NOT remove the clue." if f2 else ""))
    lines.append("Mitigations that work: cut the audio so gaps between flyovers are lost; replace the "
                 "audio track; strong noise reduction tuned to remove tonal content below about 500 Hz, "
                 "then re-check with this audit. Not reliable: a gentle high-pass; talking over it; "
                 "phone-call compression.")
    for ln in lines:
        out(ln)
    return found
