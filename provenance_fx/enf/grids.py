"""Multi-grid reference layer: free, no-login frequency logs for several synchronous grids.

Every synchronous grid wobbles on its own random pattern. When the recording time is roughly
known, correlating the recording's ENF against CONCURRENT logs of each grid (a "grid race")
identifies the grid far more decisively than statistics alone.

Sources (all free, no account, no API key; cached in ~/.cache/provenance/enf):
  GB       NESO 1 s monthly CSV (2014 -> last published month) + Elexon BMRS FREQ 15 s (recent days)
  CE       Energy-Charts (Fraunhofer ISE, Freiburg) 1 s, 2022-05-01 -> now, CC BY 4.0
           + OSF power-grid database FR01 / PL01 / IT01 (fixed weeks, 2019-2020)
  NORDIC   Fingrid 10 Hz monthly 7z archives (local Finnish time -> UTC), CC BY 4.0
           + OSF SE01
  US-WEST  OSF US_UT01 (Salt Lake City, 2019-05-19..25) + Pigott Phoenix 5 s (2022-02-14..2023-02-23)
           + Zenodo Hartmann et al. 1 s (2024-01-16..11-18) + FNET gauge scrape (2026-03-20..05-12, low trust)
           + the user's own home logger ('US West (home)')
  US-TEXAS OSF US_TX01/02 (2019-05-15..16, 2019-05-20..23) + FNET gauge scrape 2026 (low trust)
  US-EAST  OSF US_FL01 (Florida, 2023-06/07; Zenodo copy identical) + FNET gauge scrape 2026 (low trust)
  QUEBEC   FNET gauge scrape 2026 only (low trust)
  See us_refs.py for the US sources.
Not covered by any free no-login source found: live US grids, Japan, China, India, Australia,
Ireland (SEM), Baltic. (Free-with-registration sources are listed in README, not used.)
"""
from __future__ import annotations

import datetime as dt
import glob
import io
import json
import os
import zoneinfo

import numpy as np

from . import reference as R
from . import us_refs as US
from provenance_fx.enf.reference import DATA as _DATA  # noqa: E402

CACHE = R.CACHE
OSF_DIR = os.environ.get("PROVENANCE_OSF_DIR", os.path.join(_DATA, "osf_pgfdb"))
ENERGY_CHARTS = "https://api.energy-charts.info/frequency?region=DE-Freiburg&start={a}&end={b}"
FINGRID = "https://data.fingrid.fi/files/339/{y}/{y}-{m:02d}.7z"

GRIDS = {
    "GB": dict(name="Great Britain (GB)", nominal=50, live=True,
               sources="NESO 1 s archive + Elexon 15 s recent"),
    "CE": dict(name="Continental Europe", nominal=50, live=True,
               sources="Energy-Charts 1 s (Freiburg, from 2022-05) + OSF FR01/PL01/IT01"),
    "NORDIC": dict(name="Nordic", nominal=50, live=False,
                   sources="Fingrid 10 Hz monthly archives (published ~1 month later) + OSF SE01"),
    "US-WEST": dict(name="US Western Interconnection", nominal=60, live=False,
                    sources="OSF US_UT01 (May 2019) + Pigott Phoenix 5 s (2022-23) + Zenodo 1 s (2024) "
                            "+ FNET gauge scrape (Mar-May 2026, low trust) + your home logger"),
    "US-TEXAS": dict(name="US Texas (ERCOT)", nominal=60, live=False,
                     sources="OSF US_TX01/02 (May 2019) + FNET gauge scrape (Mar-May 2026, low trust)"),
    "US-EAST": dict(name="US Eastern Interconnection", nominal=60, live=False,
                    sources="OSF US_FL01 (Jun-Jul 2023) + FNET gauge scrape (Mar-May 2026, low trust)"),
    "QUEBEC": dict(name="Quebec (Hydro-Quebec)", nominal=60, live=False,
                   sources="FNET gauge scrape only (Mar-May 2026, low trust)"),
}
OSF_FILES = {"CE": ["FR01", "PL01", "IT01"], "NORDIC": ["SE01"], "US-WEST": ["US_UT01"],
             "US-TEXAS": ["US_TX01", "US_TX02"], "US-EAST": ["US_FL01"], "GB": ["GB01"]}

_OSF_CACHE = {}


def _osf(code):
    if code in _OSF_CACHE:
        return _OSF_CACHE[code]
    npz = os.path.join(CACHE, "osf", code + ".npz")
    if os.path.exists(npz):
        z = np.load(npz)
        r = R.Reference(float(z["t0"]), 1.0, z["f"], "OSF " + code, int(z["nominal"]), False, "OSF " + code, 1.0)
    else:
        p = os.path.join(OSF_DIR, code, code + ".csv")
        if not os.path.exists(p):
            _OSF_CACHE[code] = None
            return None
        nominal = 60 if code.startswith("US") else 50
        r = R.from_csv(p, nominal=nominal)
        r.name = r.source = "OSF " + code
        os.makedirs(os.path.dirname(npz), exist_ok=True)
        np.savez_compressed(npz, t0=r.t0, f=r.f.astype(np.float32), nominal=nominal)
    _OSF_CACHE[code] = r
    return r


# ---------------------------------------------------------------- Energy-Charts (CE, 1 s)

def energy_charts_day(day: dt.date, log=None):
    d = os.path.join(CACHE, "energycharts")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"ce_{day.isoformat()}.npz")
    today = dt.datetime.now(dt.timezone.utc).date()
    if os.path.exists(p) and (day < today - dt.timedelta(days=1)
                              or dt.datetime.now().timestamp() - os.path.getmtime(p) < 120):
        z = np.load(p)
        return R.Reference(float(z["t0"]), 1.0, z["f"], "CE (Energy-Charts)", 50, False, "Energy-Charts 1 s", 1.0) if len(z["f"]) else None
    if day < dt.date(2022, 5, 1):
        return None
    a = dt.datetime.combine(day, dt.time(0), dt.timezone.utc)
    url = ENERGY_CHARTS.format(a=a.strftime("%Y-%m-%dT%H:%MZ"),
                               b=(a + dt.timedelta(hours=23, minutes=59, seconds=59)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    (log or (lambda m: None))(f"Energy-Charts CE frequency {day}")
    import urllib.error
    try:
        with R._get(url, timeout=120) as r:
            js = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        js = {}  # Energy-Charts has no data for this day
    u = np.array(js.get("unix_seconds") or [], dtype=float)
    v = np.array([np.nan if x is None else x for x in (js.get("data") or [])], dtype=float)
    if len(u) == 0:
        np.savez_compressed(p, t0=0.0, f=np.array([], np.float32))
        return None
    n = int(u[-1] - u[0]) + 1
    g = np.full(n, np.nan)
    g[(u - u[0]).astype(int)] = v
    g[(g < 45) | (g > 55)] = np.nan
    np.savez_compressed(p, t0=u[0], f=g.astype(np.float32))
    return R.Reference(float(u[0]), 1.0, g, "CE (Energy-Charts)", 50, False, "Energy-Charts 1 s", 1.0)


# ---------------------------------------------------------------- Fingrid (Nordic, 10 Hz)

def _fingrid_day_csv(text: bytes, tz=zoneinfo.ZoneInfo("Europe/Helsinki")):
    lines = text.split(b"\n")[1:]
    lines = [ln for ln in lines if len(ln) > 24]
    if not lines:
        return None
    ts = np.array([ln[:19] for ln in lines], dtype="S19")
    vals = np.array([ln.split(b",", 1)[1] for ln in lines]).astype(float)
    a = ts.view(np.uint8).reshape(-1, 19).astype(np.int64) - 48
    hh = a[:, 11] * 10 + a[:, 12]
    mm = a[:, 14] * 10 + a[:, 15]
    ss = a[:, 17] * 10 + a[:, 18]
    sec_local = hh * 3600 + mm * 60 + ss
    day = dt.date(int(ts[0][:4]), int(ts[0][5:7]), int(ts[0][8:10]))
    base = dt.datetime.combine(day, dt.time(0))
    # local -> UTC per row; on the autumn change the repeated hour is fold=1 after the time goes backwards
    back = np.where(np.diff(sec_local) < 0)[0]
    fold = np.zeros(len(sec_local), bool)
    if len(back):
        fold[back[0] + 1:] = True
    utc = np.empty(len(sec_local), float)
    for h in np.unique(hh):
        for f in (False, True):
            m = (hh == h) & (fold == f)
            if not m.any():
                continue
            loc = (base + dt.timedelta(hours=int(h))).replace(tzinfo=tz, fold=int(f))
            off = loc.utcoffset().total_seconds()
            utc[m] = base.replace(tzinfo=dt.timezone.utc).timestamp() + sec_local[m] - off
    sec = np.floor(utc).astype(np.int64)
    s0 = sec.min()
    idx = sec - s0
    cnt = np.bincount(idx)
    sm = np.bincount(idx, weights=vals)
    with np.errstate(invalid="ignore"):
        f = sm / cnt
    f[cnt < 5] = np.nan
    f[(f < 45) | (f > 55)] = np.nan
    return float(s0), f


def fingrid_month(y, m, log=None):
    d = os.path.join(CACHE, "fingrid")
    os.makedirs(d, exist_ok=True)
    npz = os.path.join(d, f"nordic_{y}-{m:02d}.npz")
    if os.path.exists(npz):
        z = np.load(npz)
        return R.Reference(float(z["t0"]), 1.0, z["f"], "Nordic (Fingrid)", 50, False, "Fingrid 10 Hz -> 1 s", 1.0)
    arch = os.path.join(d, f"{y}-{m:02d}.7z")
    miss = arch + ".missing"
    if os.path.exists(miss) and dt.datetime.now().timestamp() - os.path.getmtime(miss) < 6 * 3600:
        return None  # checked recently: not published yet (Fingrid posts each month ~weeks later)
    if not os.path.exists(arch):
        (log or (lambda s: None))(f"downloading Fingrid {y}-{m:02d} (~65 MB)")
        try:
            with R._get(FINGRID.format(y=y, m=m), timeout=900) as r, open(arch + ".part", "wb") as fh:
                while True:
                    b = r.read(1 << 22)
                    if not b:
                        break
                    fh.write(b)
            os.replace(arch + ".part", arch)
        except Exception as e:
            (log or (lambda s: None))(f"Fingrid {y}-{m:02d} unavailable: {e}")
            open(miss, "w").write(str(e))
            return None
    try:
        import py7zr  # optional dependency (pip install provenance-forensics[enf-nordic]), only for Nordic
    except ImportError:
        (log or (lambda s: None))("Nordic reference needs py7zr: pip install py7zr")
        return None
    (log or (lambda s: None))(f"unpacking Fingrid {y}-{m:02d}")
    parts = []
    with py7zr.SevenZipFile(arch) as z:
        names = sorted(n for n in z.getnames() if n.endswith(".csv"))
        tmp = os.path.join(d, f"tmp_{y}{m:02d}")
        z.extractall(path=tmp)
    for n in names:
        p = os.path.join(tmp, n)
        out = _fingrid_day_csv(open(p, "rb").read())
        if out:
            parts.append(R.Reference(out[0], 1.0, out[1], "Nordic", 50, False, "Fingrid", 1.0))
    import shutil
    import subprocess
    subprocess.run(["chmod", "-R", "u+rwx", tmp], check=False)
    shutil.rmtree(tmp, ignore_errors=True)
    ref = R.concat(parts, "Nordic (Fingrid)")
    ref.source = "Fingrid 10 Hz -> 1 s"
    np.savez_compressed(npz, t0=ref.t0, f=ref.f.astype(np.float32))
    return ref


# ---------------------------------------------------------------- unified access

def _months(start, end):
    s = dt.datetime.fromtimestamp(start, dt.timezone.utc)
    e = dt.datetime.fromtimestamp(end, dt.timezone.utc)
    y, m = s.year, s.month
    while (y, m) <= (e.year, e.month):
        yield y, m
        y, m = (y + (m == 12), m % 12 + 1)


def grid_reference(grid, start, end, log=None, allow_download=True, tz_shift_h=0.0):
    """Concurrent reference for `grid` covering [start, end] (unix s), or None if not covered.
    tz_shift_h: extra clock offset tried for sources whose time zone is uncertain (US Pigott log)."""
    log = log or (lambda m: None)
    parts = []
    try:
        if grid == "GB":
            try:
                parts.append(R.gb_reference(start, end, log=log))
            except Exception as e:
                log(f"GB: {e}")
        elif grid == "CE":
            d = dt.datetime.fromtimestamp(start, dt.timezone.utc).date()
            d1 = dt.datetime.fromtimestamp(end, dt.timezone.utc).date()
            while d <= d1:
                r = energy_charts_day(d, log) if allow_download or os.path.exists(
                    os.path.join(CACHE, "energycharts", f"ce_{d.isoformat()}.npz")) else None
                if r is not None:
                    parts.append(r.slice(start, end))
                d += dt.timedelta(days=1)
        elif grid == "NORDIC":
            for y, m in _months(start - 3 * 3600, end + 3 * 3600):
                if not allow_download and not os.path.exists(os.path.join(CACHE, "fingrid", f"nordic_{y}-{m:02d}.npz")):
                    continue
                r = fingrid_month(y, m, log)
                if r is not None:
                    parts.append(r.slice(start, end))
    except Exception as e:
        log(f"{grid}: download failed ({e})")
    osf_present = []
    for code in OSF_FILES.get(grid, []):
        r = _osf(code)
        if r is not None:
            osf_present.append(code)
        if r is not None and r.t0 <= end and r.t1 >= start:
            parts.append(r.slice(start, end))
    try:
        parts += US.references(grid, start, end, tz_shift_h=tz_shift_h, osf_present=osf_present)
    except Exception as e:
        log(f"{grid}: US reference failed ({e})")
    parts = [p for p in parts if p is not None and len(p.f) and np.isfinite(p.f).mean() > 0.2]
    if not parts:
        return None
    ref = R.concat(parts, GRIDS[grid]["name"]) if len(parts) > 1 else parts[0].to_1s()
    ref.name = GRIDS[grid]["name"]
    ref.nominal = GRIDS[grid]["nominal"]
    return ref.slice(start, end)


def coverage():
    """Human-readable coverage table for README / GUI."""
    rows = []
    for g, info in GRIDS.items():
        osf = []
        for code in OSF_FILES.get(g, []):
            r = _osf(code)
            if r is not None:
                osf.append(f"{code}: {r.label_time(r.t0)[:10]}..{r.label_time(r.t1)[:10]}")
        spans = []
        for code in OSF_FILES.get(g, []):
            r = _osf(code)
            if r is not None:
                spans.append(dict(source="OSF " + code, start=r.label_time(r.t0)[:10], end=r.label_time(r.t1)[:10],
                                  good_hours=round(float(np.isfinite(r.f).sum()) / 3600, 1), resolution_s=1.0, trust=1.0,
                                  tz_uncertain=False, duplicate_of=None))
        spans += US.coverage(g)
        live = dict(GB="NESO monthly 1 s from 2014 + Elexon 15 s up to today",
                    CE="Energy-Charts 1 s from 2022-05-01 up to today (downloaded per day)",
                    NORDIC="Fingrid 10 Hz monthly archives, published about a month late").get(g)
        rows.append(dict(grid=g, name=info["name"], nominal=info["nominal"], sources=info["sources"], osf=osf,
                         spans=spans, live=live))
    return rows
