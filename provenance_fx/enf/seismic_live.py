"""Live seismic grid-frequency collector ("gridwatch" tier A).

One SeedLink connection over secure WebSocket (wss://rtserve.earthscope.org/seedlink, port 443) carries
every station. Each minute the collector tracks the hum line of each station; every 10-minute UTC window
it runs the agreement gate (seismic.Gate, causal), takes the consensus of trusted stations and appends
the window to today's file <SEISMIC_DIR>/<GRID>/YYYY-MM-DD.csv. At UTC midnight the finished day is
gzipped. A status file (status.json) and the log show stations up, trusted count and coverage; it warns
when fewer than 3 stations are trusted.

Waveforms are kept only in a short in-memory ring buffer (40 min) and never written to disk.

  provenance enf-collect                       # run until stopped (same as python -m provenance_fx.enf.seismic_live)
  provenance enf-collect --minutes 120         # run for two hours
  provenance enf-collect --sdr-config sdr.json # also run the optional part-time SDR cross-check

EarthScope rules followed: SeedLink for live data (never polling dataselect), a single connection
(their limit is 5), and a polite reconnect back-off. Whether anonymous SeedLink stays open after the
2026-12-15 account change is [VERIFY].
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import gzip
import json
import logging
import os
import shutil
import signal
import time

import numpy as np

from . import mseed
from . import seismic as S

SEEDLINK_WSS = os.environ.get("PROVENANCE_SEEDLINK", "wss://rtserve.earthscope.org/seedlink")
BACKFILL_MIN = 30          # ask the server's ring buffer for the last 30 min at start (bootstraps the gate)
RING_S = 40 * 60
TRACK_EVERY_S = 60
LATENCY_MARGIN_S = 45      # wait this long after a window ends before closing it
STALL_S = 120              # no packet for this long = silent dead connection (e.g. after a sleep): reconnect
log = logging.getLogger("seismic_live")


class Rolling:
    """Per-second values over the last `keep` seconds, indexed by integer UTC second."""

    def __init__(self, keep=6 * 3600):
        self.keep = keep
        self.t0 = None
        self.f = np.zeros(0)

    def put(self, T, F):
        if len(T) == 0:
            return
        if self.t0 is None:
            self.t0 = int(T[0]) - 60
            self.f = np.full(self.keep, np.nan)
        hi = int(T[-1])
        if hi - self.t0 >= self.keep:          # slide forward
            sh = hi - self.t0 - self.keep + 3600
            self.f = np.concatenate([self.f[sh:], np.full(sh, np.nan)])
            self.t0 += sh
        i = T.astype(np.int64) - self.t0
        m = (i >= 0) & (i < self.keep)
        self.f[i[m]] = F[m]

    def get(self, a, b):
        out = np.full(b - a, np.nan)
        if self.t0 is None:
            return out
        i0, i1 = a - self.t0, b - self.t0
        lo, hi = max(i0, 0), min(i1, self.keep)
        if hi > lo:
            out[lo - i0:hi - i0] = self.f[lo:hi]
        return out


class Collector:
    def __init__(self, stations=None, out_dir=None, grids=None):
        self.stations = stations or [s[0] for s in S.STATIONS if s[0].split(".")[0] not in S.EXCLUDED_NETWORKS]
        self.grid_of = {s[0]: S.assign_grid(s[1], s[2]) for s in S.STATIONS}
        self.grids = sorted({self.grid_of.get(s, "US-WEST") for s in self.stations}) if grids is None else grids
        if out_dir:
            S.SEISMIC_DIR = out_dir
        self.recs = {sid: [] for sid in self.stations}
        self.last_sample = {}
        self.tracks = {sid: Rolling() for sid in self.stations}
        self.gates = {g: S.Gate([s for s in self.stations if self.grid_of.get(s) == g]) for g in self.grids}
        self.restored = self.load_gate_state()
        self.next_window = None
        self.n_packets = 0
        self.connected_since = None
        self.stats = dict(started=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                          reconnects=0, windows=0, rows=0)
        self.accepted = set()
        self._tracked_once = set()
        self.tracked_to = {}

    # ------------------------------------------------------------ ingest
    async def run_seedlink(self, stop):
        import websockets
        backoff = 5
        while not stop.is_set():
            try:
                async with websockets.connect(SEEDLINK_WSS, open_timeout=30, ping_interval=None,
                                              max_size=None) as ws:
                    await self._handshake(ws)
                    self.connected_since = time.time()
                    backoff = 5
                    buf = bytearray()
                    last_rx = time.time()
                    while not stop.is_set():
                        try:
                            m = await asyncio.wait_for(ws.recv(), 30)
                        except asyncio.TimeoutError:
                            if time.time() - last_rx > STALL_S:
                                raise ConnectionError(f"no data for {STALL_S} s")
                            continue
                        last_rx = time.time()
                        buf += m if isinstance(m, (bytes, bytearray)) else m.encode()
                        while len(buf) >= 8 and buf[:2] == b"SL":
                            if len(buf) < 520:
                                break
                            self._packet(bytes(buf[8:520]))
                            del buf[:520]
                        if buf and buf[:2] != b"SL":
                            j = buf.find(b"SL")
                            log.warning("SeedLink stream out of step, skipping %d bytes", j if j > 0 else len(buf))
                            del buf[:j if j > 0 else len(buf)]
            except Exception as e:
                self.stats["reconnects"] += 1
                log.warning("SeedLink connection lost (%s); retrying in %d s", e, backoff)
                try:
                    await asyncio.wait_for(stop.wait(), backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 300)

    async def _handshake(self, ws):
        now = time.time()
        self.accepted = set()
        for sid in self.stations:
            net, sta, loc, cha = sid.split(".")
            since = self.last_sample.get(sid, now - BACKFILL_MIN * 60) - 10
            start = dt.datetime.fromtimestamp(since, dt.timezone.utc).strftime("%Y,%m,%d,%H,%M,%S")
            ok = True
            for cmd in (f"STATION {sta} {net}", f"SELECT {loc}{cha}.D" if loc else f"SELECT {cha}.D", f"TIME {start}"):
                await ws.send(cmd + "\r\n")
                r = await asyncio.wait_for(ws.recv(), 20)
                r = r if isinstance(r, (bytes, bytearray)) else r.encode()
                if b"OK" not in r:
                    log.info("%s: server answered %r to %s; skipping station", sid, r[:40], cmd.split()[0])
                    ok = False
                    break
            if ok:
                self.accepted.add(sid)
        await ws.send("END\r\n")
        log.info("SeedLink: streaming %d of %d stations: %s", len(self.accepted), len(self.stations),
                 ", ".join(sorted(self.accepted)))

    def _packet(self, rec_bytes):
        rec, _ = mseed.parse_header(rec_bytes)
        if rec is None or rec.sid not in self.recs:
            return
        self.n_packets += 1
        lst = self.recs[rec.sid]
        lst.append(rec)
        end = rec.start + rec.nsamp / rec.fs if rec.fs else rec.start
        self.last_sample[rec.sid] = max(self.last_sample.get(rec.sid, 0), end)
        cut = self.last_sample[rec.sid] - RING_S
        if len(lst) > 50 and lst[0].start < cut:
            self.recs[rec.sid] = [r for r in lst if r.start >= cut]

    # ------------------------------------------------------------ processing
    def track_all(self, look_back_s=240):
        for sid, lst in self.recs.items():
            hi = self.last_sample.get(sid, 0)
            if sid in self._tracked_once:
                # after a reconnect the stream resumes from the last sample, so the new stretch can be long
                lb = min(RING_S, max(look_back_s, hi - self.tracked_to.get(sid, hi) + 60))
            else:
                lb = RING_S
            self._tracked_once.add(sid) if lst else None
            if not lst:
                continue
            self.tracked_to[sid] = hi
            use = [r for r in lst if r.start >= hi - lb - S.FRAME_S - 5]
            if not use:
                continue
            for seg in mseed.to_segments(use):
                T, F, Sn = S.track_segment(seg, S.harmonic_of(sid))
                F = np.where((Sn >= S.MIN_SNR_DB) & (np.abs(F - 60) < 0.5), F, np.nan)
                self.tracks[sid].put(T, F)

    def close_windows(self, now=None):
        now = now or time.time()
        if self.next_window is None:
            # first window: the oldest complete window covered by the backfill
            self.next_window = int((now - BACKFILL_MIN * 60) // S.WINDOW_S * S.WINDOW_S)
            if getattr(self, "resume_from", 0) > self.next_window:   # those windows were written by the last run
                self.next_window = int(self.resume_from)
        while self.next_window + S.WINDOW_S + LATENCY_MARGIN_S <= now:
            a, b = self.next_window, self.next_window + S.WINDOW_S
            latest = max(self.last_sample.values(), default=0)
            if self.last_sample and latest < b - 5 and now - b < RING_S - 2 * S.WINDOW_S:
                # the stream is behind (stall or reconnect in progress): hold the window until the
                # resumed stream has filled it, as long as the ring buffer can still hold it
                break
            for g in self.grids:
                ids = [s for s in self.stations if self.grid_of.get(s) == g]
                ser = {i: self.tracks[i].get(a, b) for i in ids}
                gate = self.gates[g]
                res = gate.evaluate(ser)
                use = gate.trusted()
                weights = {i: res.get(i, (gate.st[i]["r"], 0))[0] for i in use}
                weights = {i: (0.5 if not np.isfinite(w) else w) for i, w in weights.items()}
                lags = {i: gate.st[i]["lag"] for i in ids}
                f, cnt, spread = S.consensus_window(ser, use, weights, lags)
                q = np.where(cnt >= 3, "good", np.where(cnt == 2, "fair", np.where(cnt == 1, "single", "none")))
                rows = self.append_rows(g, a + S.LABEL_SHIFT_S, f, cnt, spread, q)
                self.stats["rows"] += rows
                self.write_status(g, a, res, use, rows)
                self.save_gate_state(g, b)
                if len(use) < 3:
                    log.warning("%s window %s: only %d trusted stations (%s)", g, _hm(a), len(use), ", ".join(use) or "none")
                else:
                    log.info("%s window %s: %d trusted, %d s written", g, _hm(a), len(use), rows)
            self.stats["windows"] += 1
            self.next_window = b

    def append_rows(self, grid, t0, f, cnt, spread, q):
        n = 0
        by_day = {}
        for k in range(len(f)):
            if not np.isfinite(f[k]):
                continue
            ts = t0 + k
            day = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
            sp = "" if not np.isfinite(spread[k]) else f"{spread[k]:.2f}"
            by_day.setdefault(day, []).append(
                f"{dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},{f[k]:.6f},{int(cnt[k])},{sp},{q[k]}\n")
            n += 1
        for day, lines in by_day.items():
            p = S.day_path(grid, day, gz=False)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if os.path.exists(p + ".gz") and not os.path.exists(p):
                # a finished (archive-built) day exists: start the live file from it so nothing is lost
                with gzip.open(p + ".gz", "rt") as src, open(p, "w") as dst:
                    shutil.copyfileobj(src, dst)
                os.remove(p + ".gz")
            new = not os.path.exists(p)
            with open(p, "a") as fh:
                if new:
                    fh.write(S.HEADER)
                fh.writelines(lines)
        return n

    def roll_days(self, now=None):
        """gzip the live .csv files of finished UTC days (keeping rows sorted and unique)."""
        today = dt.datetime.fromtimestamp(now or time.time(), dt.timezone.utc).date()
        for g in self.grids:
            d = os.path.join(S.SEISMIC_DIR, g)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if fn.endswith(".csv") and fn[:-4] < today.isoformat():
                    p = os.path.join(d, fn)
                    rows = []
                    if os.path.exists(p + ".gz"):      # an archive-built file for the same day: merge, live rows win
                        with gzip.open(p + ".gz", "rt") as fh:
                            rows = fh.read().splitlines()[1:]
                    with open(p) as fh:
                        rows += fh.read().splitlines()[1:]
                    uniq = sorted({r[:20]: r for r in rows if r and r[0].isdigit()}.values())
                    with gzip.open(p + ".gz.tmp", "wt") as fh:
                        fh.write(S.HEADER)
                        fh.write("\n".join(uniq) + "\n")
                    os.replace(p + ".gz.tmp", p + ".gz")
                    os.remove(p)
                    log.info("rolled %s (%d rows)", p + ".gz", len(uniq))

    GATE_MAX_AGE_S = 3600   # a saved gate younger than this is reused at start (skips the warm-up)

    def _gate_path(self, grid):
        return os.path.join(S.SEISMIC_DIR, grid, "gate_state.json")

    def save_gate_state(self, grid, window_end):
        st = {i: {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in s.items()}
              for i, s in self.gates[grid].st.items()}
        p = self._gate_path(grid)
        with open(p + ".tmp", "w") as fh:
            json.dump(dict(window_end=window_end, stations=st), fh, default=float)
        os.replace(p + ".tmp", p)

    def load_gate_state(self, now=None):
        """Reuse the trust states of a recent run, so a restart writes data from its first window."""
        now = now or time.time()
        got = []
        for g, gate in self.gates.items():
            p = self._gate_path(g)
            try:
                d = json.load(open(p))
            except (OSError, ValueError):
                continue
            if now - float(d.get("window_end", 0)) > self.GATE_MAX_AGE_S:
                continue
            for i, s in d.get("stations", {}).items():
                if i in gate.st:
                    s = dict(s)
                    s["r"] = np.nan if s.get("r") is None else float(s["r"])
                    s["lags"] = [int(x) for x in s.get("lags", [])]
                    s["lag"] = int(s.get("lag", 0))
                    gate.st[i].update(s)
            got.append(g)
            self.resume_from = max(getattr(self, "resume_from", 0), int(d["window_end"]))
        if got:
            log.info("reusing gate states from the last run (%s), no warm-up needed", ", ".join(got))
        return got

    def write_status(self, grid, a, res, use, rows):
        st = dict(grid=grid, window_start=_iso(a), updated=_iso(time.time()), trusted=use,
                  stations={i: dict(state=self.gates[grid].st[i]["state"], r=_r(res.get(i, (np.nan, 0))[0]),
                                    lag_s=self.gates[grid].st[i]["lag"],
                                    last_sample=_iso(self.last_sample[i]) if i in self.last_sample else None)
                            for i in self.gates[grid].st},
                  rows_this_window=rows, streaming=sorted(self.accepted), packets=self.n_packets, **self.stats)
        p = os.path.join(S.SEISMIC_DIR, grid, "status.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w") as fh:
            json.dump(st, fh, indent=1)
        os.replace(p + ".tmp", p)

    async def run_processing(self, stop):
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), TRACK_EVERY_S)
            except asyncio.TimeoutError:
                pass
            try:
                await asyncio.to_thread(self.track_all)
                self.close_windows()
                self.roll_days()
            except Exception:
                log.exception("processing step failed")


def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds")


def _hm(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _r(v):
    return None if v is None or not np.isfinite(v) else round(float(v), 3)


async def amain(args):
    col = Collector(out_dir=args.out_dir)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sg in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sg, stop.set)
        except NotImplementedError:
            pass
    tasks = [asyncio.create_task(col.run_seedlink(stop)), asyncio.create_task(col.run_processing(stop))]
    if args.sdr_config:
        from . import seismic_sdr
        tasks.append(asyncio.create_task(seismic_sdr.run_schedule(args.sdr_config, col, stop)))
    if args.minutes:
        async def timer():
            await asyncio.sleep(args.minutes * 60)
            stop.set()
        tasks.append(asyncio.create_task(timer()))
    await stop.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    col.track_all()
    col.close_windows(time.time() + 0)   # flush complete windows
    log.info("stopped: %s", col.stats)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--minutes", type=float, default=None, help="stop after this many minutes")
    ap.add_argument("--out-dir", default=None, help=f"default {S.SEISMIC_DIR}")
    ap.add_argument("--sdr-config", default=None, help="JSON list of OpenWebRX receivers for the part-time cross-check")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(amain(a))


if __name__ == "__main__":
    main()
