"""US grid references beyond the OSF weeks: free, no-login, real measured logs.

Raw files live in PROVENANCE_US_DIR (default $PROVENANCE_DATA/us, i.e. ~/provenance-data/us); `build_all()` turns them into
compact NPZ caches in ~/.cache/provenance/enf/us, which is what the grid race loads.

  US-WEST   zenodo_wecc_2024   De Din, Carta, Hartmann, Zenodo 10.5281/zenodo.17366693,
                               CC BY 4.0. 1 s, 2024-01-16..2024-11-18 UTC, site not published [VERIFY].
                               Rows flagged QI=2 (linearly filled gaps) are dropped, never used.
            pigott_phx_2022    John Pigott (jp3141), Phoenix AZ, OSF osf.io/cq285 (60Hz.log.gz), no license stated.
                               5 s cycle counts against a GPS-disciplined clock, 2022-02-14..2023-02-23.
                               Timestamps are the Pi's local clock; offset to UTC inferred, see PIGOTT_TZ_H.
            nategriff_wecc     nate-griff/enf on GitHub: FNET public gauge images read back to numbers,
                               2026-03-20..2026-05-12. LOW TRUST (pixel quantised, clipped at +-50 mHz).
            home_west          the user's own logger (home_logger/), 'US West (home)'.
  US-EAST   zenodo_east_2023   same Zenodo record; verified identical to OSF US_FL01 (r = 1.0000), so it is
                               only used when US_FL01 is not on disk.
            nategriff_ei       FNET gauge scrape, low trust.
  US-TEXAS  nategriff_ercot    FNET gauge scrape, low trust.
  QUEBEC    nategriff_quebec   FNET gauge scrape, low trust.
  seismic_* 'US West (seismic)' etc.: consensus of public seismometers that pick up mains hum, rebuilt
            from the FDSN archive or collected live (provenance_fx/enf/seismic.py, seismic_live.py). Day files in
            ~/.cache/provenance/enf/us/seismic/<GRID>/YYYY-MM-DD.csv(.gz). Trust 0.9: derived, but GPS-timed
            and checked station against station. Where a measured log covers the same second, it wins.
Set PROVENANCE_US_DISABLE=key1,key2 (or us_refs.DISABLED) to leave sources out, e.g. to race the seismic
reference in place of Zenodo during validation.
"""
from __future__ import annotations

import datetime as dt
import glob
import gzip
import os
import struct
import zlib

import numpy as np

from . import reference as R
from provenance_fx.enf.reference import DATA as _DATA  # noqa: E402

RAW = os.environ.get("PROVENANCE_US_DIR", os.path.join(_DATA, "us"))
CACHE = os.path.join(R.CACHE, "us")
HOME_DIR = os.environ.get("PROVENANCE_HOME_LOGS", os.path.join(CACHE, "home"))

# Pigott's logger stamps rows with the Raspberry Pi's local clock (datetime.now()). Phoenix keeps
# MST (UTC-7) all year. The offset was checked against the 2024 Zenodo WECC log's daily cycle
# (scripts/enf_pigott_tz.py, enf_validation.md); it is still [VERIFY] with the author.
PIGOTT_TZ_H = -7.0
TZ_SEARCH_H = (-1.0, 1.0, 7.0)   # extra offsets (hours, relative to the assumed one) the race may try
NG_CLIP_HZ = 0.0495               # FNET gauge axis is 59.95..60.05 Hz; values at the edge are clipped
NG_TRUST = 0.5
SEISMIC_TRUST = 0.9
NG_GRIDS = {"WECC": "nategriff_wecc", "EI": "nategriff_ei", "ERCOT": "nategriff_ercot", "Quebec": "nategriff_quebec"}

SOURCES = {
    "zenodo_wecc_2024": dict(grid="US-WEST", label="Zenodo 2024 (De Din, Carta, Hartmann) 1 s", trust=1.0, res=1.0),
    "pigott_phx_2022": dict(grid="US-WEST", label="Pigott, Phoenix AZ 2022-23, 5 s", trust=0.9, res=5.0, tz=True),
    "nategriff_wecc": dict(grid="US-WEST", label="FNET gauge scrape (nate-griff) 2026, low trust", trust=NG_TRUST, res=2.0),
    "home_west": dict(grid="US-WEST", label="US West (home)", trust=1.0, res=1.0),
    "zenodo_east_2023": dict(grid="US-EAST", label="Zenodo 2023 (= OSF US_FL01)", trust=1.0, res=1.0, dup_of="US_FL01"),
    "nategriff_ei": dict(grid="US-EAST", label="FNET gauge scrape (nate-griff) 2026, low trust", trust=NG_TRUST, res=2.0),
    "nategriff_ercot": dict(grid="US-TEXAS", label="FNET gauge scrape (nate-griff) 2026, low trust", trust=NG_TRUST, res=2.0),
    "nategriff_quebec": dict(grid="QUEBEC", label="FNET gauge scrape (nate-griff) 2026, low trust", trust=NG_TRUST, res=2.0),
    "seismic_west": dict(grid="US-WEST", label="US West (seismic)", trust=SEISMIC_TRUST, res=1.0, seismic=True),
    "seismic_texas": dict(grid="US-TEXAS", label="US Texas (seismic)", trust=SEISMIC_TRUST, res=1.0, seismic=True),
    "seismic_east": dict(grid="US-EAST", label="US East (seismic)", trust=SEISMIC_TRUST, res=1.0, seismic=True),
}
DISABLED = set(k for k in os.environ.get("PROVENANCE_US_DISABLE", "").split(",") if k)

_MEM = {}


def _npz(key):
    return os.path.join(CACHE, key + ".npz")


def _save(key, t0, step, f):
    os.makedirs(CACHE, exist_ok=True)
    np.savez_compressed(_npz(key), t0=float(t0), step=float(step), f=np.asarray(f, np.float32))


# ---------------------------------------------------------------- builders (raw -> NPZ)

def _zip_member_text(path):
    """A single deflated zip member saved by byte range (local header + data).
    A plain extracted CSV (optionally .gz) is accepted too."""
    b = open(path, "rb").read()
    if b[:2] == b"\x1f\x8b":
        import gzip
        return gzip.decompress(b)
    if b[:4] != b"PK\x03\x04":
        if b[:4] == b"Time":          # already-extracted 'Time;f60;QI' CSV
            return b
        raise ValueError(f"{path}: not a zip local file header or a Zenodo CSV")
    n, m = struct.unpack("<HH", b[26:30])
    return zlib.decompressobj(-15).decompress(b[30 + n + m:])


def parse_zenodo_csv(text: bytes):
    """Zenodo 'Time;f60;QI' (UTC, mHz deviation). Keeps only QI=0 rows; QI=2 are filled-in gaps."""
    lines = [ln for ln in text.split(b"\n")[1:] if len(ln) > 20]
    ts = np.array([ln[:19] for ln in lines], dtype="S19").astype("datetime64[s]").astype(np.int64)
    parts = [ln.split(b";") for ln in lines]
    v = np.array([p[1] for p in parts], dtype=float)
    q = np.array([p[2].strip() for p in parts])
    t0 = int(ts.min())
    f = np.full(int(ts.max()) - t0 + 1, np.nan)
    good = q == b"0"
    f[ts[good] - t0] = 60.0 + v[good] / 1000.0
    return float(t0), f, dict(rows=len(lines), good=int(good.sum()))


def build_zenodo(key, member_path):
    t0, f, st = parse_zenodo_csv(_zip_member_text(member_path))
    _save(key, t0, 1.0, f)
    return st


def parse_pigott(lines, tz_h=PIGOTT_TZ_H, step=5.0):
    """Pigott log rows: 'YYYY-mm-dd HH:MM:SS.fff, ticks, cycles, freq, ...' in local clock time."""
    import re
    pat = re.compile(rb"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}),\s*\d+,\s*\d+,\s*([0-9.]+),")
    ts, fs = [], []
    for ln in lines:
        m = pat.match(ln)
        if m:
            ts.append(m.group(1)); fs.append(float(m.group(2)))
    t = np.array(ts, dtype="S23").astype("datetime64[ms]").astype(np.int64) / 1000.0 - tz_h * 3600.0
    keep = (t > 1.5e9) & (t < 2.0e9)            # drops the odd corrupted line
    t, fs = t[keep], np.array(fs)[keep]
    f = np.array(fs, float)
    f[(f < 59.5) | (f > 60.5)] = np.nan
    # each value is the mean over the PRECEDING ~5 s; centre it on its interval
    t = t - step / 2
    t0 = np.floor(t.min() / step) * step
    i = np.round((t - t0) / step).astype(np.int64)
    g = np.full(int(i.max()) + 1, np.nan)
    g[i] = f
    return float(t0), g


def build_pigott(path=None):
    path = path or os.path.join(RAW, "pigott_60Hz.log.gz")
    with gzip.open(path, "rb") as fh:
        t0, g = parse_pigott(fh.read().split(b"\n"), tz_h=0.0)   # cache in raw local clock; offset applied on load
    _save("pigott_phx_2022", t0, 5.0, g)
    return dict(samples=int(np.isfinite(g).sum()))


def parse_nategriff(text: bytes):
    """nate-griff CSV: timestamp_utc,region,frequency_hz (blank = gauge unreadable). -> {region: (t0, f1s)}."""
    out = {}
    rows = [ln.split(b",") for ln in text.split(b"\n")[1:] if ln.count(b",") == 2]
    by = {}
    for ts, reg, v in rows:
        v = v.strip()
        if not v:
            continue
        by.setdefault(reg.decode(), []).append((ts[:19], float(v)))
    for reg, vals in by.items():
        t = np.array([a for a, _ in vals], dtype="S19").astype("datetime64[s]").astype(np.int64)
        f = np.array([b for _, b in vals])
        out[reg] = (t, f)
    return out


def clip_mask(f, tol=NG_CLIP_HZ, pad=3):
    """NaN out gauge-clipped samples (at the 59.95 / 60.05 Hz axis edge) and `pad` s either side."""
    f = f.copy()
    bad = np.isfinite(f) & (np.abs(f - 60.0) >= tol)
    if bad.any():
        k = np.convolve(bad.astype(float), np.ones(2 * pad + 1), "same") > 0
        f[k] = np.nan
    return f


def build_nategriff(folder=None):
    folder = folder or os.path.join(RAW, "nategriff")
    acc = {}
    for p in sorted(glob.glob(os.path.join(folder, "20*.csv"))):
        for reg, (t, f) in parse_nategriff(open(p, "rb").read()).items():
            acc.setdefault(reg, []).append((t, f))
    st = {}
    for reg, key in NG_GRIDS.items():
        if reg not in acc:
            continue
        t = np.concatenate([a for a, _ in acc[reg]]); f = np.concatenate([b for _, b in acc[reg]])
        t0 = int(t.min())
        i = t - t0
        cnt = np.bincount(i); sm = np.bincount(i, weights=f)
        with np.errstate(invalid="ignore"):
            g = sm / cnt
        raw_ok = np.isfinite(g).sum()
        g = clip_mask(g)
        _save(key, t0, 1.0, g)
        st[key] = dict(samples=int(raw_ok), after_clip_mask=int(np.isfinite(g).sum()))
    return st


def build_all(log=print):
    st = {}
    for key, names in (("zenodo_wecc_2024", ("wi_member.bin", "zenodo_west.csv", "zenodo_west.csv.gz")),
                       ("zenodo_east_2023", ("ei_member.bin", "zenodo_east.csv", "zenodo_east.csv.gz"))):
        found = [os.path.join(RAW, n) for n in names if os.path.exists(os.path.join(RAW, n))]
        if found:
            st[key] = build_zenodo(key, found[0])
    if os.path.exists(os.path.join(RAW, "pigott_60Hz.log.gz")):
        st["pigott_phx_2022"] = build_pigott()
    if glob.glob(os.path.join(RAW, "nategriff", "20*.csv")):
        st.update(build_nategriff())
    log(st)
    _MEM.clear()
    return st


# ---------------------------------------------------------------- the user's own logger

def load_home():
    """Merge every imported home-logger NPZ (home_logger/import_to_provenance.py writes them)."""
    parts = []
    for p in sorted(glob.glob(os.path.join(HOME_DIR, "*.npz"))):
        z = np.load(p)
        parts.append(R.Reference(float(z["t0"]), float(z["step"]) if "step" in z else 1.0, z["f"].astype(float),
                                 "US West (home)", 60, False, "US West (home)", 1.0))
    if not parts:
        return None
    ref = R.concat(parts, "US West (home)") if len(parts) > 1 else parts[0]
    ref.source = "US West (home)"
    return ref


# ---------------------------------------------------------------- loaders

def load(key, tz_shift_h=0.0):
    """Reference for one source (None if its cache is missing). tz_shift_h only affects tz-uncertain sources."""
    info = SOURCES[key]
    if key in DISABLED:
        return None
    if key == "home_west":
        return load_home()
    if info.get("seismic"):
        from . import seismic as SZ
        r = SZ.load_reference(info["grid"], label=info["label"])
        if r is not None:
            r.trust, r.resolution_s = info["trust"], info["res"]
        return r
    if key not in _MEM:
        p = _npz(key)
        if not os.path.exists(p):
            _MEM[key] = None
        else:
            z = np.load(p)
            _MEM[key] = (float(z["t0"]), float(z["step"]), z["f"])
    if _MEM[key] is None:
        return None
    t0, step, f = _MEM[key]
    if info.get("tz"):
        t0 = t0 - (PIGOTT_TZ_H + tz_shift_h) * 3600.0
    return R.Reference(t0, step, f, info["label"], 60, False, info["label"], info["res"], info["trust"],
                       bool(info.get("tz")))


def sources_for(grid):
    return [k for k, v in SOURCES.items() if v["grid"] == grid]


def references(grid, start, end, tz_shift_h=0.0, osf_present=()):
    """Slices of every US source of `grid` overlapping [start, end]."""
    out = []
    for k in sources_for(grid):
        dup = SOURCES[k].get("dup_of")
        if dup and dup in osf_present:
            continue
        r = load(k, tz_shift_h)
        if r is None or r.t0 > end or r.t1 < start:
            continue
        out.append(r.slice(start, end))
    return out


def any_tz_uncertain(grid, start, end):
    for k in sources_for(grid):
        if SOURCES[k].get("tz"):
            r = load(k)
            if r is not None and r.t0 <= end and r.t1 >= start:
                return True
    return False


def coverage(grid):
    """[(label, start_date, end_date, good_hours, trust)] for the GUI and README."""
    rows = []
    for k in sources_for(grid):
        if SOURCES[k].get("seismic") and k not in DISABLED:
            rows += _seismic_coverage(k)
            continue
        r = load(k)
        if r is None:
            continue
        ok = np.isfinite(r.f)
        if not ok.any():
            continue
        i = np.where(ok)[0]
        lab = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
        rows.append(dict(source=SOURCES[k]["label"], key=k, start=lab(r.time_of(i[0])), end=lab(r.time_of(i[-1])),
                         good_hours=round(float(ok.sum() * r.step / 3600), 1), resolution_s=r.resolution_s,
                         trust=r.trust, tz_uncertain=r.tz_uncertain, duplicate_of=SOURCES[k].get("dup_of")))
    return rows


def _seismic_coverage(key):
    """One coverage row per run of consecutive day files (seismic days are rebuilt piecemeal)."""
    from . import seismic as SZ
    info = SOURCES[key]
    days = []
    for name, paths in SZ.day_files(info["grid"]):
        n = 0
        for p in paths:
            key_ = (p, os.path.getmtime(p))
            if key_ not in SZ._DAYCACHE:
                SZ._DAYCACHE[key_] = SZ.read_day_file(p)
            n = max(n, int(np.isfinite(SZ._DAYCACHE[key_][1]).sum()))
        if n:
            days.append((dt.date.fromisoformat(name), n))
    rows, run = [], []
    for d, n in days + [(None, 0)]:
        if run and (d is None or d - run[-1][0] > dt.timedelta(days=1)):
            rows.append(dict(source=info["label"], key=key, start=run[0][0].isoformat(), end=run[-1][0].isoformat(),
                             good_hours=round(sum(x[1] for x in run) / 3600, 1), resolution_s=1.0, trust=info["trust"],
                             tz_uncertain=False, duplicate_of=None))
            run = []
        if d is not None:
            run.append((d, n))
    return rows
