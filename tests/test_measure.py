import numpy as np

from provenance_fx import measure, spectro
from provenance_fx.physics import straight_line_curve


def _tone(f_of_t, sr, amp, rng, noise=0.05):
    phase = 2 * np.pi * np.cumsum(f_of_t) / sr
    return amp * np.sin(phase) + noise * rng.normal(size=len(f_of_t))


def test_fit_recovers_speed_distance_and_pitch():
    rng = np.random.default_rng(0)
    sr, dur = 2000, 160.0
    t = np.arange(int(sr * dur)) / sr
    f0, v, d, tc = 95.0, 80.0, 900.0, 80.0
    f = straight_line_curve(t, f0, v, d, tc)
    x = _tone(f, sr, 0.03, rng)
    spec = spectro.compute(x, sr)
    m = measure.fit_event(spec, 5, 155, fmax=250)
    assert abs(m.f0 - f0) / f0 < 0.01
    assert abs(m.speed - v) / v < 0.08
    assert abs(m.slant_cpa - d) / d < 0.25
    assert abs(m.t_cpa - tc) < 2.0
    assert m.speed_range[0] <= v <= m.speed_range[1]
    assert m.slant_range[0] <= d <= m.slant_range[1]


def test_event_detection_finds_faint_pass():
    rng = np.random.default_rng(1)
    sr = 2000
    t = np.arange(sr * 400) / sr
    f = straight_line_curve(t, 90.0, 90.0, 700.0, 200.0)
    env = np.exp(-((t - 200) / 40) ** 2)
    x = 0.03 * env * np.sin(2 * np.pi * np.cumsum(f) / sr) + 0.05 * rng.normal(size=len(t))
    spec = spectro.compute(x, sr)
    ev = spectro.detect_events(spec)
    assert len(ev) == 1 and ev[0][0] < 200 < ev[0][1]
