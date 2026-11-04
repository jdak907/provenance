import numpy as np

from provenance_fx import audit
from provenance_fx.physics import straight_line_curve


def _clip(rng, sr=2000):
    t = np.arange(sr * 300) / sr
    x = 0.05 * rng.normal(size=len(t))
    for tc, f0 in ((80, 95.0), (220, 85.0)):
        f = straight_line_curve(t, f0, 85.0, 600.0, tc)
        env = np.exp(-((t - tc) / 35) ** 2)
        x += 0.03 * env * np.sin(2 * np.pi * np.cumsum(f) / sr)
    return x


def test_audit_finds_curves_and_highpass_does_not_remove_them():
    rng = np.random.default_rng(3)
    sr = 2000
    x = _clip(rng, sr)
    _, found = audit.scan(x, sr)
    assert len(found) == 2
    # the video's point: a gentle high-pass plus re-boost leaves the curve detectable
    y = audit.highpass(x, sr, 150.0, order=2)
    _, found2 = audit.scan(y, sr)
    assert len(found2) >= 1
