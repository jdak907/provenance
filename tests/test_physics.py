import numpy as np

from provenance_fx.physics import (doppler, emission_times, heard_frequency, naive_frequency,
                            straight_line_curve, straight_line_extremes)


class Line:
    """Straight, constant-speed flight along +x at height h, offset y0."""

    def __init__(self, v=90.0, y0=600.0, h=800.0, t_cpa=0.0):
        self.v, self.y0, self.h, self.tc = v, y0, h, t_cpa

    def pos(self, t):
        t = np.asarray(t, float)
        return np.stack([self.v * (t - self.tc), np.full_like(t, self.y0), np.full_like(t, self.h)], -1)

    def vel(self, t):
        t = np.asarray(t, float)
        return np.stack([np.full_like(t, self.v), np.zeros_like(t), np.zeros_like(t)], -1)


def test_doppler_sign():
    assert doppler(100, -50) > 100 > doppler(100, 50)


def test_emission_time_solves_propagation():
    m = Line()
    obs = np.zeros((50, 3))
    t_rx = np.linspace(-60, 60, 50)
    te = emission_times(m, obs, t_rx)
    r = np.linalg.norm(m.pos(te) - obs, axis=-1)
    assert np.allclose(te + r / 343.0, t_rx, atol=1e-6)


def test_straight_line_closed_form_matches_numeric_model():
    v, y0, h = 85.0, 700.0, 900.0
    m = Line(v, y0, h)
    d = np.hypot(y0, h)
    t_rx = np.linspace(-80, 80, 400)
    f_num, _, _ = heard_frequency(m, np.zeros((400, 3)), t_rx, 100.0)
    f_cf = straight_line_curve(t_rx, 100.0, v, d, d / 343.0)
    assert np.max(np.abs(f_num - f_cf)) < 1e-4
    # heard CPA (delayed by d/c) is exactly the base pitch
    assert abs(straight_line_curve(np.array([d / 343.0]), 100.0, v, d, d / 343.0)[0] - 100.0) < 1e-9
    hi, lo = straight_line_extremes(100.0, v)
    assert f_cf[0] < hi and f_cf[-1] > lo and f_cf[0] > 120 and f_cf[-1] < 85


def test_naive_model_is_a_different_curve_not_just_a_delay():
    m = Line(95.0, 300.0, 700.0)
    d = np.hypot(300.0, 700.0)
    t = np.linspace(-60, 60, 481)
    good, _, _ = heard_frequency(m, np.zeros((481, 3)), t, 100.0)
    bad = naive_frequency(m, np.zeros((481, 3)), t, 100.0)
    # best possible time shift of the naive curve still leaves an error of several Hz
    errs = []
    for s in np.arange(-40, 41):
        a = good[max(0, s):len(good) + min(0, s)]
        b = bad[max(0, -s):len(bad) + min(0, -s)]
        errs.append(np.max(np.abs(a - b)))
    assert min(errs) > 1.0
