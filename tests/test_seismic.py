"""Tests for the seismic grid reference: miniSEED decoding, hum tracking, agreement gate, day files,
the race registration and the live collector's file handling. No network needed."""
import datetime as dt
import gzip
import os
import struct

import numpy as np
import pytest

from provenance_fx.enf import mseed, seismic as S

HERE = os.path.dirname(__file__)


def test_steim2_matches_obspy_fixture():
    segs = mseed.read_segments(open(os.path.join(HERE, "data", "sl_sample.mseed"), "rb").read())
    ref = np.load(os.path.join(HERE, "data", "sl_sample_obspy.npz"))
    assert len(segs) == 1
    s = segs[0]
    assert s.sid == "NN.HYDE..HNZ" and s.fs == 200.0
    assert np.array_equal(s.data.astype(np.int64), ref["NN.HYDE..HNZ"])
    assert abs(s.start - float(ref["NN.HYDE..HNZ_t0"])) < 1e-5


def _int32_record(start, vals, fs=200, sta="TEST", net="XX", cha="HHZ", little=False):
    e = "<" if little else ">"
    t = dt.datetime.fromtimestamp(start, dt.timezone.utc)
    hdr = b"000001D " + sta.ljust(5).encode() + b"  " + cha.encode() + net.encode()
    hdr += struct.pack(e + "HHBBBBH", t.year, t.timetuple().tm_yday, t.hour, t.minute, t.second, 0, t.microsecond // 100)
    hdr += struct.pack(e + "Hhh", len(vals), fs, 1) + bytes([0, 0, 0, 1]) + struct.pack(e + "iHH", 0, 64, 48)
    blk = struct.pack(e + "HH", 1000, 0) + bytes([3, 0 if little else 1, 9, 0])
    data = np.asarray(vals, e + "i4").tobytes()
    rec = hdr + blk + b"\0" * (64 - 48 - 8) + data
    return rec + b"\0" * (512 - len(rec))


@pytest.mark.parametrize("little", [False, True])
def test_int32_records_join_into_one_segment(little):
    v1, v2 = np.arange(100), np.arange(100, 200)
    buf = _int32_record(1700000000.0, v1, little=little) + _int32_record(1700000000.5, v2, little=little)
    segs = mseed.read_segments(buf)
    assert len(segs) == 1 and np.array_equal(segs[0].data, np.arange(200)) and segs[0].sid == "XX.TEST..HHZ"


def _hum(fs, f_of_t, dur, start=1700000000.0, harmonic=1, noise=1.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(dur * fs)) / fs
    phase = 2 * np.pi * harmonic * np.cumsum(f_of_t(t)) / fs
    return mseed.Segment("XX.T..HHZ", start, fs, 5 * np.sin(phase) + noise * rng.normal(size=len(t)))


@pytest.mark.parametrize("fs,h", [(200.0, 1), (100.0, 1), (200.0, 2)])
def test_tracker_recovers_grid_frequency_including_aliases(fs, h):
    f = lambda t: 60 + 0.02 * np.sin(2 * np.pi * t / 120)
    seg = _hum(fs, f, 600, harmonic=h)
    T, F, snr = S.track_segment(seg, harmonic=h)
    truth = f(T - seg.start)
    assert len(T) > 580 and np.median(snr) > 20
    assert np.sqrt(np.mean((F - truth) ** 2)) < 0.0015          # under 1.5 mHz
    assert np.corrcoef(F, truth)[0, 1] > 0.99


def _walk(n, seed):
    """Grid-like frequency: mean-reverting random walk with second-to-second detail (about 15 mHz spread)."""
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.995 * x[i - 1] + rng.normal(0, 0.0015)
    return 60 + x


def test_gate_trusts_agreeing_stations_drops_lookalike_and_learns_lag():
    n = 6 * 600
    truth = _walk(n, 1)
    rng = np.random.default_rng(2)
    tr = {f"good{i}": truth + rng.normal(0, 0.002, n) for i in range(4)}
    tr["late"] = S._shift(truth, -1) + rng.normal(0, 0.002, n)     # station whose clock reads 1 s late
    tr["fake"] = _walk(n, 99)                                          # instrument tone: looks fine, does not track
    c = S.build_consensus(tr, 0, n)
    used = {i for pw in c["per_window"] for i in pw["used"]}
    assert "fake" not in used and {"good0", "good1", "good2", "good3", "late"} <= used
    assert c["lags"]["late"] == 1          # its values must be read 1 s later to line up
    m = np.isfinite(c["f"])
    assert m.mean() > 0.95
    assert np.sqrt(np.mean((c["f"][m] - truth[m]) ** 2)) < 0.002
    # the causal (live) rule needs three passing windows before it trusts anyone
    cc = S.build_consensus(tr, 0, n, causal=True)
    assert np.isnan(cc["f"][:2 * 600]).all() and np.isfinite(cc["f"][3 * 600:]).mean() > 0.95


def test_no_consensus_from_disagreeing_stations():
    n = 4 * 600
    tr = {f"s{i}": _walk(n, 10 + i) for i in range(3)}
    c = S.build_consensus(tr, 0, n)
    assert np.isnan(c["f"]).all()


def test_day_file_roundtrip_and_race_registration(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SEISMIC_DIR", str(tmp_path))
    day = dt.date(2025, 7, 1)
    d0 = int(dt.datetime(2025, 7, 1, tzinfo=dt.timezone.utc).timestamp())
    f = 60 + 0.01 * np.sin(np.arange(86400) / 500)
    f[100:200] = np.nan
    n = np.full(86400, 4)
    p, rows = S.write_day("US-WEST", day, d0, f, n, np.full(86400, 1.0), np.full(86400, "good"))
    assert rows == 86300 and p.endswith("2025-07-01.csv.gz")
    t0, g, nn = S.read_day_file(p)
    assert t0 == d0 and np.allclose(g[np.isfinite(f)], f[np.isfinite(f)], atol=1e-6) and np.isnan(g[150])
    from provenance_fx.enf import grids as G, us_refs as U
    r = U.load("seismic_west")
    assert r is not None and r.source == "US West (seismic)" and r.trust == U.SEISMIC_TRUST
    ref = G.grid_reference("US-WEST", d0 + 3600, d0 + 7200, allow_download=False)
    assert ref is not None and "US West (seismic)" in ref.source
    U.DISABLED.add("seismic_west")
    try:
        assert U.load("seismic_west") is None
    finally:
        U.DISABLED.discard("seismic_west")


def test_concat_prefers_higher_trust_where_logs_overlap():
    from provenance_fx.enf import reference as R
    a = R.Reference(0.0, 1.0, np.full(100, 60.01), source="measured", trust=1.0)
    b = R.Reference(50.0, 1.0, np.full(100, 60.02), source="seismic", trust=0.9)
    c = R.concat([a, b])
    assert c.f[60] == 60.01 and c.f[120] == 60.02


def test_live_append_and_midnight_roll_merge_with_archive_file(tmp_path, monkeypatch):
    from provenance_fx.enf import seismic_live as L
    monkeypatch.setattr(S, "SEISMIC_DIR", str(tmp_path))
    col = L.Collector(stations=["PB.B088..HHZ", "NN.HYDE..HNZ"], grids=["US-WEST"])
    day = dt.date(2026, 11, 2)
    d0 = int(dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc).timestamp())
    # archive-built file for the morning
    f = np.full(86400, np.nan); f[:600] = 60.0
    S.write_day("US-WEST", day, d0, f, np.full(86400, 3), np.full(86400, 1.0), np.full(86400, "good"))
    # live rows later that day (one overlapping second must win)
    col.append_rows("US-WEST", d0 + 599, np.full(10, 60.01), np.full(10, 2), np.full(10, 0.5), np.full(10, "fair"))
    ref = S.load_reference("US-WEST")
    assert ref.f[int(d0 + 599 - ref.t0)] == pytest.approx(60.01) and ref.f[int(d0 + 10 - ref.t0)] == 60.0
    col.roll_days(now=d0 + 86400 + 60)
    assert not os.path.exists(S.day_path("US-WEST", day, gz=False))
    _, g, n = S.read_day_file(S.day_path("US-WEST", day))
    assert np.isfinite(g).sum() == 609 and g[599] == pytest.approx(60.01) and n[605] == 2


def test_assign_grid_and_licence_exclusion():
    assert S.assign_grid(33.6, -116.6) == "US-WEST"       # Anza
    assert S.assign_grid(31.7, -103.5) == "US-TEXAS"      # Permian Basin
    assert S.assign_grid(40.0, -80.0) == "US-EAST"
    with pytest.raises(ValueError):
        S.fetch_fdsn("AM.R0000.00.EHZ", 0, 10)            # Raspberry Shake: never fetched


def test_sdr_hum_track_uses_fitted_clock():
    from provenance_fx.enf import seismic_sdr as SD
    fs_true = 11976.0                                       # receiver audio runs 0.2 % slow
    dur = 120
    t = np.arange(int(dur * fs_true)) / fs_true
    f = 60 + 0.02 * np.sin(2 * np.pi * t / 40)
    x = (3000 * np.sin(2 * np.pi * 2 * np.cumsum(f) / fs_true)).astype(np.int16)   # 120 Hz harmonic
    t0 = 1700000000.0
    idx = np.arange(0, len(x), 2048)
    stamps = np.column_stack([t0 + idx / fs_true, idx]).astype(float)
    T, F, h, snr = SD.hum_track(x, stamps)
    assert h == 120
    truth = 60 + 0.02 * np.sin(2 * np.pi * (T - t0) / 40)
    assert np.corrcoef(F, truth)[0, 1] > 0.98 and np.sqrt(np.mean((F - truth) ** 2)) < 0.003


def test_cli_has_enf_collect_and_rebuild(capsys):
    import pytest
    from provenance_fx import cli
    for cmd in ("enf-collect", "enf-rebuild"):
        with pytest.raises(SystemExit) as e:
            cli.main([cmd, "--help"])
        assert e.value.code == 0


def test_apply_continuity_reports_first_segment_start_on_break():
    from provenance_fx.enf import match as M
    m = dict(start_time=1000.0, label="strong", warnings=[])
    c = dict(jumps=1, segments=[dict(t=0, shift_s=-8.0, ncc=0.92), dict(t=300, shift_s=1.0, ncc=0.99)])
    M.apply_continuity(m, c)
    assert m["timeline_break"] and m["start_time_first_segment"] == 992.0 and m["start_time"] == 1000.0
    assert any(w.startswith("timeline break") for w in m["warnings"])
    m2 = dict(start_time=5.0, warnings=[])
    M.apply_continuity(m2, dict(jumps=0, segments=[]))
    assert "timeline_break" not in m2


def test_live_collector_holds_windows_while_stream_is_behind(tmp_path, monkeypatch):
    from provenance_fx.enf import seismic as S
    from provenance_fx.enf import seismic_live as L
    monkeypatch.setattr(S, "SEISMIC_DIR", S.SEISMIC_DIR)   # restored after the test
    col = L.Collector(out_dir=str(tmp_path))
    a = 1_800_000_000 // 600 * 600
    col.next_window = a
    sid = col.stations[0]
    col.last_sample = {sid: a + 100}            # stream stalled 100 s into the window
    col.close_windows(now=a + 700)
    assert col.next_window == a                 # held, not written off as empty
    col.last_sample = {sid: a + 650}            # resumed stream caught up
    col.close_windows(now=a + 700)
    assert col.next_window == a + 600


def test_live_gate_state_survives_restart(tmp_path, monkeypatch):
    import time
    from provenance_fx.enf import seismic as S
    from provenance_fx.enf import seismic_live as L
    monkeypatch.setattr(S, "SEISMIC_DIR", S.SEISMIC_DIR)
    col = L.Collector(out_dir=str(tmp_path))
    g = "US-WEST"
    sid = next(iter(col.gates[g].st))
    col.gates[g].st[sid].update(state="trusted", good=5, lag=1, lags=[1, 1])
    os_dir = tmp_path / g
    os_dir.mkdir(parents=True, exist_ok=True)
    end = int(time.time()) // 600 * 600
    col.save_gate_state(g, end)
    col2 = L.Collector(out_dir=str(tmp_path))
    assert g in col2.restored and col2.gates[g].st[sid]["state"] == "trusted" and col2.gates[g].st[sid]["lag"] == 1
    col2.close_windows(now=end + 30)            # nothing complete yet, but the first window resumes at `end`
    assert col2.next_window == end
