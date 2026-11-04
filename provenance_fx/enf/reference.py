"""ENF reference data: the built-in GB grid (NESO 1 s archive + Elexon 15 s recent feed),
any user CSV, or a WAV recorded straight from the mains.

All references become a regular grid: Reference(t0, step, f). t0 is unix seconds (UTC)
for dated data, or 0 with relative=True for undated data (for example ENF-WHU).

Data credits: "Supported by National Energy SO Open Data" (NESO Open Data Licence).
Elexon BMRS FREQ data: Elexon Insights Solution, BMRS open data license [VERIFY exact wording].
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
import urllib.request
from dataclasses import dataclass

import numpy as np

CACHE = os.path.join(os.path.expanduser("~/.cache/provenance"), "enf")
# Downloaded raw datasets (ENF-WHU, OSF weeks, US logs, sample clips). See DATA_SOURCES.md.
DATA = os.environ.get("PROVENANCE_DATA", os.path.expanduser("~/provenance-data"))
NESO_PACKAGE = "https://api.neso.energy/api/3/action/package_show?id=system-frequency-data"
ELEXON_FREQ = ("https://data.elexon.co.uk/bmrs/api/v1/datasets/FREQ?measurementDateTimeFrom={a}"
               "&measurementDateTimeTo={b}&format=json")
UA = {"User-Agent": "provenance-enf/0.1 (local research tool)"}


@dataclass
class Reference:
    t0: float                 # unix seconds of f[0] (or 0 when relative)
    step: float               # seconds between samples
    f: np.ndarray             # Hz (NaN = gap)
    name: str = "reference"
    nominal: int = 50
    relative: bool = False
    source: str = ""
    resolution_s: float = 1.0  # native resolution before any re-gridding
    trust: float = 1.0         # 1 = measured, GPS-timed; lower = derived or rough data (race weights it down)
    tz_uncertain: bool = False  # timestamps may sit a whole number of hours off (race searches offsets)

    @property
    def t1(self):
        return self.t0 + self.step * (len(self.f) - 1)

    def time_of(self, idx):
        return self.t0 + idx * self.step

    def label_time(self, ts):
        if self.relative:
            return f"+{ts:.1f} s into the reference"
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def slice(self, a=None, b=None):
        i0 = 0 if a is None else max(0, int(np.floor((a - self.t0) / self.step)))
        i1 = len(self.f) if b is None else min(len(self.f), int(np.ceil((b - self.t0) / self.step)) + 1)
        return Reference(self.time_of(i0), self.step, self.f[i0:i1], self.name, self.nominal,
                         self.relative, self.source, self.resolution_s, self.trust, self.tz_uncertain)

    def to_1s(self):
        if abs(self.step - 1.0) < 1e-9:
            return self
        n = int(np.floor((len(self.f) - 1) * self.step)) + 1
        tt = np.arange(n, dtype=float)
        src = np.arange(len(self.f)) * self.step
        ok = np.isfinite(self.f)
        g = np.interp(tt, src[ok], self.f[ok]) if ok.sum() > 1 else np.full(n, np.nan)
        # keep gaps: a 1 s sample is NaN when its nearest native sample is NaN
        near = np.clip(np.round(tt / self.step).astype(int), 0, len(self.f) - 1)
        g[~ok[near]] = np.nan
        return Reference(self.t0, 1.0, g, self.name, self.nominal, self.relative, self.source, self.resolution_s,
                         self.trust, self.tz_uncertain)

    def info(self):
        return dict(name=self.name, source=self.source, nominal=self.nominal, relative=self.relative,
                    start=None if self.relative else self.label_time(self.t0),
                    end=None if self.relative else self.label_time(self.t1),
                    hours=round(len(self.f) * self.step / 3600, 2), step_s=self.step,
                    resolution_s=self.resolution_s, trust=self.trust, tz_uncertain=self.tz_uncertain, gaps_pct=round(100 * float(np.mean(~np.isfinite(self.f))), 2))


def concat(refs, name=None):
    refs = [r.to_1s() for r in refs if r is not None and len(r.f)]
    if not refs:
        raise ValueError("no reference data")
    refs.sort(key=lambda r: r.t0)
    t0, t1 = refs[0].t0, max(r.t1 for r in refs)
    n = int(round(t1 - t0)) + 1
    f = np.full(n, np.nan)
    for r in sorted(refs, key=lambda r: (r.trust, r.t0)):   # higher-trust logs are written last, so they win overlaps
        i = int(round(r.t0 - t0))
        seg = f[i:i + len(r.f)]
        m = np.isfinite(r.f[:len(seg)])
        seg[m] = r.f[:len(seg)][m]
    return Reference(t0, 1.0, f, name or refs[0].name, refs[0].nominal, False,
                     " + ".join(sorted({r.source for r in refs})), max(r.resolution_s for r in refs),
                     min(r.trust for r in refs), any(r.tz_uncertain for r in refs))


# ---------------------------------------------------------------- generic CSV

_TIME_NAMES = ("dtm", "time", "timestamp", "datetime", "date", "utc", "ts", "t", "measurementtime", "time_utc",
               "timestamp_utc")
_FREQ_NAMES = ("f", "freq", "frequency", "hz", "f50", "f60", "value", "enf", "frequency_hz", "freq_hz")


def _parse_times(vals):
    vals = [v.strip().strip('"') for v in vals]
    try:
        x = np.array(vals, dtype=float)
        if np.nanmedian(x) > 1e11:      # milliseconds
            x = x / 1000.0
        return x
    except ValueError:
        pass
    clean = [v.replace("Z", "").replace("T", " ").split("+")[0] for v in vals]
    clean = [re.sub(r"\.(\d+)$", "", v) for v in clean]
    try:
        arr = np.array(clean, dtype="datetime64[s]")
    except ValueError:
        arr = np.array([np.datetime64(dt.datetime.fromisoformat(v)) for v in clean], dtype="datetime64[s]")
    return arr.astype("int64").astype(float)


def from_csv(path_or_text, nominal=None, name=None, time_col=None, freq_col=None, units="auto",
             qi_bad=True) -> Reference:
    """Read a time,frequency CSV (comma, semicolon or tab). Times: ISO (UTC) or unix seconds.

    Frequency: absolute Hz (e.g. 50.012), or deviation in mHz from nominal (OSF power-grid
    database style: column 'f60' holding -12.3 means 59.9877 Hz). units: auto | hz | mhz_dev | hz_dev.
    Rows whose quality column (QI*) is non-zero are treated as gaps.
    """
    if isinstance(path_or_text, str) and os.path.exists(path_or_text):
        text = open(path_or_text, "r", encoding="utf-8", errors="replace").read()
        nm = name or os.path.basename(path_or_text)
    else:
        text = path_or_text if isinstance(path_or_text, str) else path_or_text.decode()
        nm = name or "uploaded.csv"
    first = text[:4096]
    delim = ";" if first.count(";") > first.count(",") else ("\t" if first.count("\t") > first.count(",") else ",")
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    rows = [r for r in rows if r and any(c.strip() for c in r)]
    header = [c.strip().lower() for c in rows[0]]
    has_header = any(re.search(r"[a-df-z]", c) for c in header)  # letters other than e (exponent)
    body = rows[1:] if has_header else rows
    if not has_header:
        header = [f"c{i}" for i in range(len(rows[0]))]

    def pick(names, given, default):
        if given is not None:
            return header.index(given.lower()) if isinstance(given, str) else int(given)
        for i, h in enumerate(header):
            hh = re.sub(r"_us_.*|_[a-z]{2}\d+.*", "", h)
            if hh in names or h in names:
                return i
        return default

    ti = pick(_TIME_NAMES, time_col, 0)
    fi = pick(_FREQ_NAMES, freq_col, 1 if ti == 0 else 0)
    if fi == ti:
        fi = 1 if ti == 0 else 0
    qi = next((i for i, h in enumerate(header) if h.startswith("qi")), None) if qi_bad else None
    body = [r for r in body if len(r) > max(ti, fi)]
    t = _parse_times([r[ti] for r in body])
    v = np.array([float(r[fi]) if r[fi].strip() not in ("", "nan", "NaN") else np.nan for r in body])
    if qi is not None:
        bad = np.array([(r[qi].strip() not in ("0", "0.0", "")) if len(r) > qi else False for r in body])
        v[bad] = np.nan
    hname = header[fi]
    if nominal is None:
        m = re.search(r"f(50|60)", hname)
        if m:
            nominal = int(m.group(1))
    med = float(np.nanmedian(v))
    if units == "auto":
        if 45 <= med <= 65:
            units = "hz"
        elif abs(med) < 1.0 and np.nanmax(np.abs(v)) < 2.0 and "60" not in hname and "50" not in hname:
            units = "hz_dev"
        else:
            units = "mhz_dev"
    if units == "hz":
        f = v
        nominal = nominal or (50 if med < 55 else 60)
    else:
        if nominal is None:
            raise ValueError("CSV holds frequency deviations; say whether the grid is 50 or 60 Hz")
        f = nominal + (v / 1000.0 if units == "mhz_dev" else v)
    o = np.argsort(t, kind="stable")
    t, f = t[o], f[o]
    d = np.diff(t)
    dp = d[d > 0]
    step = float(np.percentile(dp, 10)) if len(dp) else 1.0     # robust to gaps
    if abs(step - round(step)) < 0.05 and step >= 1:
        step = float(round(step))
    n = int(round((t[-1] - t[0]) / step)) + 1
    g = np.full(n, np.nan)
    idx = np.round((t - t[0]) / step).astype(int)
    g[idx] = f
    relative = bool(t[0] < 1e8)  # small numbers: seconds from start, not dates
    return Reference(float(t[0]), step, g, nm, int(nominal), relative, "csv:" + nm, step)


def from_wav(path, name=None) -> Reference:
    """A recording made straight from the mains (e.g. an ENF-WHU *_ref.wav): extract and use as reference."""
    from .media import load_raw
    from .extract import extract_enf, hum_scan

    sr, x, _ = load_raw(path)
    s = hum_scan(x, sr)
    tr = extract_enf(x, sr, nominal=s["nominal"] or s["guess"], harmonics=[1], track="peak")
    return Reference(float(tr.t[0]), 1.0, tr.f, name or os.path.basename(path), tr.nominal, True,
                     "wav:" + os.path.basename(path), 1.0)


def load_any(path, nominal=None) -> Reference:
    if path.lower().endswith((".wav", ".flac", ".mp3", ".m4a")):
        return from_wav(path)
    if path.lower().endswith(".npz"):
        z = np.load(path, allow_pickle=False)
        return Reference(float(z["t0"]), float(z["step"]), z["f"], str(z.get("name", "npz")),
                         int(z.get("nominal", 50)), bool(z.get("relative", False)), "npz", float(z["step"]))
    return from_csv(path, nominal=nominal)


# ---------------------------------------------------------------- NESO (GB, 1 s, monthly files)

def _get(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout)


def neso_months(log=None):
    """{(year, month): download_url} from the NESO CKAN package (cached for a day)."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "neso_package.json")
    import time
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 86400:
        with _get(NESO_PACKAGE) as r:
            open(p, "wb").write(r.read())
    pkg = json.load(open(p))["result"]
    out = {}
    for res in pkg["resources"]:
        m = re.search(r"f(?:new)?-(\d{4})-(\d{1,2})\.csv", res.get("url", ""))
        if m:
            out[(int(m.group(1)), int(m.group(2)))] = res["url"]
    return out


def neso_month(year, month, log=None) -> Reference:
    log = log or (lambda m: None)
    os.makedirs(os.path.join(CACHE, "neso"), exist_ok=True)
    npz = os.path.join(CACHE, "neso", f"gb_{year}-{month:02d}.npz")
    if os.path.exists(npz):
        z = np.load(npz)
        return Reference(float(z["t0"]), 1.0, z["f"], "GB (NESO)", 50, False, "NESO 1 s", 1.0)
    months = neso_months()
    if (year, month) not in months:
        raise ValueError(f"NESO has no file for {year}-{month:02d} yet")
    url = months[(year, month)]
    local = None
    for cand in (os.path.join(os.path.join(DATA, "neso"), os.path.basename(url)),):
        if os.path.exists(cand):
            local = cand
    if local is None:
        local = os.path.join(CACHE, "neso", os.path.basename(url))
        if not os.path.exists(local):
            log(f"downloading NESO {year}-{month:02d} (~70 MB) from {url}")
            with _get(url, timeout=600) as r, open(local + ".part", "wb") as fh:
                while True:
                    b = r.read(1 << 22)
                    if not b:
                        break
                    fh.write(b)
            os.replace(local + ".part", local)
    log(f"parsing {os.path.basename(local)}")
    ref = _parse_neso_csv(local)
    np.savez_compressed(npz, t0=ref.t0, f=ref.f.astype(np.float32))
    return ref


def _parse_neso_csv(path) -> Reference:
    raw = open(path, "rb").read().decode("utf-8", "replace").splitlines()
    raw = [ln for ln in raw[1:] if ln and "," in ln]
    ts = [ln.split(",", 1)[0] for ln in raw]
    fs = np.array([float(ln.split(",", 1)[1] or "nan") for ln in raw])
    t = _parse_times(ts)
    n = int(round(t[-1] - t[0])) + 1
    g = np.full(n, np.nan, dtype=np.float64)
    g[np.round(t - t[0]).astype(int)] = fs
    return Reference(float(t[0]), 1.0, g, "GB (NESO)", 50, False, "NESO 1 s", 1.0)


# ---------------------------------------------------------------- Elexon (GB, 15 s, recent)

def elexon_day(day: dt.date, log=None) -> Reference | None:
    os.makedirs(os.path.join(CACHE, "elexon"), exist_ok=True)
    p = os.path.join(CACHE, "elexon", f"freq_{day.isoformat()}.json")
    today = dt.datetime.now(dt.timezone.utc).date()
    fresh = os.path.exists(p) and (day < today - dt.timedelta(days=1) or
                                   (dt.datetime.now().timestamp() - os.path.getmtime(p)) < 120)
    if not fresh:
        a = dt.datetime.combine(day, dt.time(0), dt.timezone.utc)
        b = a + dt.timedelta(hours=23, minutes=59, seconds=59)
        url = ELEXON_FREQ.format(a=a.strftime("%Y-%m-%dT%H:%M:%SZ"), b=b.strftime("%Y-%m-%dT%H:%M:%SZ"))
        (log or (lambda m: None))(f"Elexon FREQ {day}")
        with _get(url, timeout=120) as r:
            open(p, "wb").write(r.read())
    data = json.load(open(p)).get("data", [])
    if not data:
        return None
    t = _parse_times([d["measurementTime"] for d in data])
    f = np.array([float(d["frequency"]) for d in data])
    o = np.argsort(t)
    t, f = t[o], f[o]
    n = int(round((t[-1] - t[0]) / 15.0)) + 1
    g = np.full(n, np.nan)
    g[np.round((t - t[0]) / 15.0).astype(int)] = f
    return Reference(float(t[0]), 15.0, g, "GB (Elexon 15 s)", 50, False, "Elexon BMRS FREQ 15 s", 15.0)


def gb_reference(start: float, end: float, log=None, allow_elexon=True) -> Reference:
    """GB grid reference covering [start, end] (unix s). NESO 1 s where published, Elexon 15 s otherwise."""
    log = log or (lambda m: None)
    s = dt.datetime.fromtimestamp(start, dt.timezone.utc)
    e = dt.datetime.fromtimestamp(end, dt.timezone.utc)
    try:
        avail = neso_months()
    except Exception as ex:
        log(f"NESO list unavailable ({ex}); trying Elexon only")
        avail = {}
    parts = []
    y, m = s.year, s.month
    while (y, m) <= (e.year, e.month):
        if (y, m) in avail:
            parts.append(neso_month(y, m, log).slice(start, end))
        elif allow_elexon:
            d0 = max(s.date(), dt.date(y, m, 1))
            nm = dt.date(y + (m == 12), m % 12 + 1, 1)
            d1 = min(e.date(), nm - dt.timedelta(days=1))
            d = d0
            while d <= d1:
                r = elexon_day(d, log)
                if r is not None:
                    parts.append(r.slice(start, end))
                d += dt.timedelta(days=1)
        y, m = (y + (m == 12), m % 12 + 1)
    parts = [p for p in parts if len(p.f)]
    if not parts:
        raise ValueError("no GB reference data for that window")
    ref = concat(parts, "GB grid")
    return ref.slice(start, end)
