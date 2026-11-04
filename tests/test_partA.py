"""Tests for steady-tone suppression, contrast scoring, terrain tiles and clean-up."""
from types import SimpleNamespace

import numpy as np

from provenance_fx import spectro
from provenance_fx.cleanup import CleanSettings, clean
from provenance_fx.dem_fetch import decode_terrarium, lonlat_to_tile, tile_y_to_lat
from provenance_fx.search import _bright_score

SR = 1000


def _scene(dur=240, hum=True):
    t = np.arange(int(dur * SR)) / SR
    rng = np.random.default_rng(0)
    x = 0.3 * rng.standard_normal(len(t))
    if hum:
        x += 0.5 * np.sin(2 * np.pi * 160 * t)          # steady hum all clip long
    # a 20-second sweep 120 -> 80 Hz in the middle
    m = (t > 100) & (t < 120)
    f = 120 - 40 * (t - 100) / 20
    ph = 2 * np.pi * np.cumsum(f) / SR
    x[m] += 0.5 * np.sin(ph[m])
    return x


def _bin(sp, f):
    return int(np.argmin(np.abs(sp.f - f)))


def test_steady_tone_removed_sweep_kept():
    x = _scene()
    sp = spectro.compute(x, SR, steady_window_s=60.0)
    old = spectro.compute(x, SR, steady_window_s=None)
    j = (sp.t > 20) & (sp.t < 90)                       # away from the sweep
    hum_new = sp.bright[_bin(sp, 160), j].mean()
    hum_old = old.bright[_bin(old, 160), j].mean()
    assert hum_new < 0.5 and hum_new < 0.3 * max(hum_old, 1e-9) + 0.5
    k = np.argmin(np.abs(sp.t - 110))                   # sweep is at 100 Hz here
    assert sp.bright[_bin(sp, 100), k] > 3.0


def test_contrast_rejects_curve_through_broad_patch():
    F, T = 200, 200
    Bt = np.zeros((F, T))
    Bt[:, 100:] = 4.0          # broadband bright patch in the second half
    Bt[50, :100] = 6.0         # thin line in the first half
    spec = SimpleNamespace(t=np.arange(T) * 1.0, f=np.arange(F) * 1.0, hop=1.0, df=1.0)
    fm = np.full((2, 41), 50.0)
    place = np.array([50.0, 150.0])                     # row 0 on the line, row 1 in the patch
    ev = SimpleNamespace(t_start=0.0, t_end=199.0)
    plain, _ = _bright_score(Bt, spec, fm, place, [1.0], ev, off_hz=0.0)
    con, _ = _bright_score(Bt, spec, fm, place, [1.0], ev, off_hz=4.0)
    assert plain[1] > 0.5 * plain[0]                    # brightness alone is fooled
    assert con[0] > 5.0 and con[1] < 0.5               # contrast is not


def test_terrarium_decode_and_tile_math():
    rgb = np.array([[[128, 0, 0], [128, 100, 128], [127, 255, 0]]], dtype=np.uint8)
    np.testing.assert_allclose(decode_terrarium(rgb)[0], [0.0, 100.5, -1.0])
    lat, lon = 40.876466, -73.524951
    x, y = lonlat_to_tile(lon, lat, 12)
    assert int(x) == 1211 and int(y) == 1537
    assert abs(tile_y_to_lat(y, 12) - lat) < 1e-9


def test_cleanup_reduces_hum_keeps_sweep():
    x = _scene()
    y, _ = clean(x, SR, CleanSettings(remove_steady=True, highpass_hz=40), out_sr=1000)
    a = spectro.compute(x, SR, steady_window_s=None)
    b = spectro.compute(y, 1000, steady_window_s=None)
    j = (a.t > 20) & (a.t < 90)
    hum_a = a.db[_bin(a, 160), j].mean()
    hum_b = b.db[_bin(b, 160), j[: b.db.shape[1]]].mean()
    assert hum_a - hum_b > 10                            # at least 10 dB quieter
    k = np.argmin(np.abs(b.t - 110))
    col = b.db[:, k]
    assert abs(b.f[np.argmax(col)] - 100) < 4           # sweep is now the loudest thing
    st = CleanSettings(trim_start=30, trim_end=90, remove_steady=False)
    assert abs(len(clean(x, SR, st, out_sr=1000)[0]) - 60 * 1000) < 10
