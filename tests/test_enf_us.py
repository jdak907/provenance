"""US reference layer: parsers (Zenodo QI flags, Pigott local clock, FNET gauge clipping),
low-trust and cross-nominal race rules, the clock-offset search, and long-reference time finding."""
import numpy as np

from provenance_fx.enf import extract_enf
from provenance_fx.enf import match as M
from provenance_fx.enf import reference as R
from provenance_fx.enf import us_refs as U
from provenance_fx.enf.simulate import hum_audio, random_grid


def test_zenodo_parser_drops_filled_rows():
    txt = (b"Time;f60;QI\r\n2024-01-16 23:38:35;-22.2;0\r\n2024-01-16 23:38:36;-25.5;2\r\n"
           b"2024-01-16 23:38:38;10.0;0\r\n")
    t0, f, st = U.parse_zenodo_csv(txt)
    assert t0 == 1705448315.0 and len(f) == 4
    assert abs(f[0] - 59.9778) < 1e-6 and np.isnan(f[1]) and np.isnan(f[2]) and abs(f[3] - 60.01) < 1e-9
    assert st == dict(rows=3, good=2)


def test_pigott_parser_local_clock_to_utc():
    lines = [b"2022-02-14 08:18:51.458, #",
             b"2022-02-14 08:19:00.005,  240000000,    300, 60.001000000,  47999048,  300,  16,  50, 389",
             b"2022-02-14 08:19:05.005,  240000000,    300, 59.998000000,  47999048,  600,  16,  50, 389",
             b"garbage \x00\x01, 1, 2, 3"]
    t0, g = U.parse_pigott(lines, tz_h=-7.0)
    # 08:19:00 MST = 15:19:00 UTC; value is the mean of the preceding 5 s, so centred 2.5 s earlier
    assert t0 == 1644851935.0   # 15:18:57.5 UTC floored to the 5 s grid
    assert np.nanmax(g) == 60.001 and np.isfinite(g).sum() == 2


def test_fnet_scrape_blanks_and_clip_mask():
    txt = (b"timestamp_utc,region,frequency_hz\n2026-04-19 23:59:20.03+00:00,WECC,60.01\n"
           b"2026-04-19 23:59:20.03+00:00,EI,\n2026-04-19 23:59:21.03+00:00,WECC,60.0500\n")
    out = U.parse_nategriff(txt)
    assert set(out) == {"WECC"} and len(out["WECC"][1]) == 2
    f = 60 + np.zeros(20); f[10] = 60.05
    m = U.clip_mask(f, pad=2)
    assert np.isnan(m[8:13]).all() and np.isfinite(m[:8]).all() and np.isfinite(m[13:]).all()


def _fake_us(monkeypatch, t0, n, trust=None):
    from provenance_fx.enf import grids as G
    logs = {g: random_grid(n, 60, seed=s, sigma_mhz=30) for g, s in (("US-WEST", 21), ("US-EAST", 22), ("US-TEXAS", 23))}
    logs["GB"] = random_grid(n, 50, seed=24, sigma_mhz=30)
    for g in logs:
        logs[g] = logs[g] - np.mean(logs[g]) + G.GRIDS[g]["nominal"]

    def fake(grid, start, end, log=None, allow_download=True, tz_shift_h=0.0):
        if grid not in logs:
            return None
        tr_ = (trust or {}).get(grid, 1.0)
        return R.Reference(t0, 1.0, logs[grid], grid, G.GRIDS[grid]["nominal"], False, "synthetic", 1.0, tr_).slice(start, end)
    monkeypatch.setattr(G, "grid_reference", fake)
    monkeypatch.setattr(G.US, "any_tz_uncertain", lambda *a: False)
    return logs


def test_low_trust_winner_is_capped_and_cross_nominal_control(monkeypatch):
    from provenance_fx.enf.race import grid_race
    t0, n = 1.75e9, 3 * 3600
    logs = _fake_us(monkeypatch, t0, n, trust={"US-WEST": 0.5})
    i0 = 4000
    sr, x = hum_audio(logs["US-WEST"][i0:i0 + 900], sr=1000, harmonics=((2, 0.02), (3, 0.01)), noise=0.02, seed=4)
    tr = extract_enf(x, sr, nominal=60)
    r = grid_race(tr, t0 + i0 - 1800, t0 + i0 + 1800)
    assert r["winner"] == "US-WEST" and r["decision"] == "likely" and "low-trust" in r["reason"]
    assert {x["grid"] for x in r["ranking"]} == {"US-WEST", "US-EAST", "US-TEXAS"}
    rc = grid_race(tr, t0 + i0 - 1800, t0 + i0 + 1800, cross_nominal=True)
    assert "GB" in {x["grid"] for x in rc["ranking"]} and rc["winner"] == "US-WEST"


def test_match_long_finds_time_across_chunks():
    n = 9 * 86400
    f = random_grid(n, 60, seed=31, sigma_mhz=25)
    ref = R.Reference(1.7e9, 1.0, f, "long", 60, False, "synthetic", 1.0)
    i0 = 6 * 86400 + 1234
    sr, x = hum_audio(f[i0:i0 + 600], sr=1000, harmonics=((2, 0.02),), noise=0.02, seed=5)
    tr = extract_enf(x, sr, nominal=60)
    m = M.match_long(tr, ref, chunk_s=2 * 86400)
    assert m["chunks"] >= 4 and abs(m["start_time"] - (1.7e9 + i0)) < 3
    assert m["n_trials"] > 1000 and m["second_ncc"] < m["ncc"]


def test_home_logs_are_a_us_west_source(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "HOME_DIR", str(tmp_path))
    np.savez_compressed(tmp_path / "2026-11-01.npz", t0=1.79e9, step=1.0, f=np.full(100, 60.0, np.float32))
    r = U.load("home_west")
    assert r.name == "US West (home)" and r.nominal == 60 and len(r.f) == 100
    assert "home_west" in U.sources_for("US-WEST")


def test_zenodo_reader_accepts_plain_and_gzip_csv(tmp_path):
    import gzip
    from provenance_fx.enf import us_refs as U
    txt = b"Time;f60;QI\n2024-01-16 23:38:35;-3.4;0\n2024-01-16 23:38:36;-3.1;2\n2024-01-16 23:38:37;-2.9;0\n"
    p1 = tmp_path / "zenodo_west.csv"; p1.write_bytes(txt)
    p2 = tmp_path / "zenodo_west.csv.gz"; p2.write_bytes(gzip.compress(txt))
    assert U._zip_member_text(str(p1)) == txt
    assert U._zip_member_text(str(p2)) == txt
    t0, f, st = U.parse_zenodo_csv(txt)
    assert len(f) == 3 and np.isnan(f[1]) and abs(f[0] - (60 - 0.0034)) < 1e-6
