import numpy as np

from provenance_fx import adsb
from provenance_fx.geo import DEM, LocalFrame


def test_local_frame_round_trip():
    f = LocalFrame(40.0, -83.0)
    x, y = f.to_xy(40.1, -82.9)
    lat, lon = f.to_latlon(x, y)
    assert abs(lat - 40.1) < 1e-9 and abs(lon + 82.9) < 1e-9
    assert 11000 < y < 11200 and 8400 < x < 8600


def test_csv_round_trip_and_jet_filter(tmp_path):
    t = np.arange(0, 120.0)
    tr = adsb.Track("abc-0", "abc123", "N1", "C172", t + 1.7e9, 40 + t * 1e-4, -83 + t * 1e-4, 1000 + 0 * t)
    jet = adsb.Track("def-0", "def456", "AAL1", "B738", t + 1.7e9, 40 + t * 1e-4, -83 + 0 * t, 9000 + 0 * t)
    p = tmp_path / "a.csv"
    adsb.write_csv(str(p), [tr, jet])
    back = adsb.load_csv(str(p))
    assert len(back) == 2
    by = {b.icao24: b for b in back}
    assert not by["abc123"].is_known_jet and by["def456"].is_known_jet
    m = adsb.TrackModel(by["abc123"], LocalFrame(40, -83))
    v = m.vel(np.array([1.7e9 + 60]))[0]
    assert abs(np.hypot(v[0], v[1]) - np.hypot(1e-4 * 111195, 1e-4 * 111195 * np.cos(np.radians(40)))) < 1.0


def test_sbs_parser(tmp_path):
    lines = []
    for i in range(30):
        s = f"{i:02d}"
        lines.append(f"MSG,3,1,1,A1B2C3,1,2026/09/08,20:00:{s}.000,2026/09/08,20:00:{s}.000,,3500,,,40.{1000+i},-83.{2000+i},,,0,0,0,0")
    lines.append("MSG,1,1,1,A1B2C3,1,2026/09/08,20:00:00.000,2026/09/08,20:00:00.000,N123AB,,,,,,,,,,,")
    p = tmp_path / "x.sbs"
    p.write_text("\n".join(lines))
    tr = adsb.load_sbs(str(p))
    assert len(tr) == 1 and tr[0].callsign == "N123AB"
    assert abs(tr[0].alt_m[0] - 3500 * 0.3048) < 1e-6
    assert len(tr[0].t) == 30


def test_dem_flat_and_grid():
    assert float(DEM.flat(123).elevation(np.array(40.0), np.array(-83.0))) == 123
    d = DEM(np.array([40, 41.0]), np.array([-84, -83.0]), np.array([[0, 100], [100, 200.0]]))
    assert abs(float(d.elevation(np.array(40.5), np.array(-83.5))) - 100) < 1e-6
