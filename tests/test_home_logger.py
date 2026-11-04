"""home_logger/: serial line parsers, daily CSV, converter, importer -> Provenance 'US West (home)'."""
import datetime as dt
import gzip
import os
import sys

import numpy as np

HL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "home_logger")
sys.path.insert(0, HL)
import convert_csv as C  # noqa: E402
import grid_logger as L  # noqa: E402
import import_to_provenance as I  # noqa: E402


def test_line_parsers():
    assert L.parse_pico("F,12,60,124999876,59.998721,-1.250,OK\r\n") == (59.998721, 60, "OK")
    assert L.parse_pico("F,1,0,0,0.000000,0.000,NOPPS") is None
    assert L.parse_pico("hello") is None
    t = "  239995033,    300, 59.999993000,  47999001,    223465,  16,   169,   7"
    assert L.parse_teensy(t) == (59.999993, 300, "OK")
    assert L.parse_teensy("#    Ticks, Cycles,    Frequency,      FBUS, Total Cyc, Flt, Phase, 1Hz") is None


def test_daily_csv_and_provenance_round_trip(tmp_path, monkeypatch):
    out = L.DailyCSV(str(tmp_path))
    t0 = int(dt.datetime(2026, 11, 3, 23, 59, 58, tzinfo=dt.timezone.utc).timestamp())
    for i in range(4):          # crosses UTC midnight -> two files
        out.write(t0 + i, 60.0 + i / 1000, 60, "OK", "pps")
    out.fh.close()
    files = sorted(os.listdir(tmp_path))
    assert files == ["gridfreq_2026-11-03.csv", "gridfreq_2026-11-04.csv"]
    txt = open(tmp_path / files[0]).read().splitlines()
    assert txt[0] == L.HEADER.strip() and txt[1].startswith("2026-11-03T23:59:58Z,60.000000,60,OK,pps")
    # Provenance reads it directly as a reference file
    from provenance_fx.enf import reference as R
    merged = tmp_path / "m.csv"
    assert C.convert([str(tmp_path / f) for f in files], str(merged)) == 4
    ref = R.from_csv(str(merged))
    assert ref.nominal == 60 and ref.t0 == t0 and abs(ref.f[3] - 60.003) < 1e-9
    # importer -> NPZ per day -> us_refs 'US West (home)'
    from provenance_fx.enf import us_refs as U
    home = tmp_path / "home"
    written, skipped = I.import_logs([str(tmp_path / f) for f in files], str(home))
    assert len(written) == 2 and skipped == 0
    monkeypatch.setattr(U, "HOME_DIR", str(home))
    r = U.load("home_west")
    assert r.source == "US West (home)"
    i = int(t0 - r.t0)
    assert np.allclose(r.f[i:i + 4], [60.0, 60.001, 60.002, 60.003], atol=1e-6)


def test_converter_reads_jp3141_local_time_and_gz(tmp_path):
    p = tmp_path / "60Hz.log.gz"
    with gzip.open(p, "wt") as fh:
        fh.write("2022-02-12 21:01:50.072, #\n")
        fh.write("2022-02-12 22:04:00.005,  239997705,    300, 59.999326244,  47999002,    223765,  16,   168,   7\n")
    rows = list(C.rows(str(p), tz_hours=-7))
    # 22:04:00 MST = 05:04:00 UTC next day; the row covers the 300 cycles (5 s) before it
    assert rows[0][0] == int(dt.datetime(2022, 2, 13, 5, 3, 55, tzinfo=dt.timezone.utc).timestamp())
    assert rows[0][1] == 59.999326244 and rows[0][4] == "local-clock"


def test_importer_skips_unlocked_clock(tmp_path):
    p = tmp_path / "gridfreq_2026-11-03.csv"
    p.write_text(L.HEADER + "2026-11-03T00:00:00Z,60.001000,60,OK,pps\n2026-11-03T00:00:01Z,60.002000,60,OK,unsync\n"
                 "2026-11-03T00:00:02Z,60.003000,60,NOPPS,pps\n")
    written, skipped = I.import_logs([str(p)], str(tmp_path / "h"))
    assert skipped == 2 and written[0][1] == 1
