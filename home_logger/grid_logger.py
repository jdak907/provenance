#!/usr/bin/env python3
"""Home grid-frequency logger for a Raspberry Pi 5: 1 s, UTC, one CSV per UTC day.

Reads either counter over a serial port:
  --source pico    Raspberry Pi Pico running pico/main.py (pushes one 'F,...' line per GPS second)
  --source teensy  Teensy 3.2 running jp3141/60Hz 60Hz.ino (answers a request; we ask once per UTC second)
Timestamps come from the Pi's clock, which chrony disciplines to GPS PPS (see install.sh), in UTC.

CSV columns (what Provenance's ENF tab loads as a reference, and what import_to_provenance.py reads):
  time_utc,frequency_hz,cycles,flags,clock_sync
  2026-11-03T18:00:00Z,59.998721,60,OK,pps
time_utc is the START of the 1 s interval the frequency was measured over.
clock_sync: pps (chrony locked to GPS PPS) | ntp (internet time only, ~10 ms) | unsync.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import os
import shutil
import subprocess
import sys
import time

HEADER = "time_utc,frequency_hz,cycles,flags,clock_sync\n"


def parse_pico(line: str):
    """'F,n,cycles,clock_cycles,freq,ppm,flags' -> (freq, cycles, flags) or None."""
    p = line.strip().split(",")
    if len(p) != 7 or p[0] != "F":
        return None
    try:
        f, cyc = float(p[4]), int(p[2])
    except ValueError:
        return None
    if not (55.0 < f < 65.0) or cyc < 50:
        return None
    return f, cyc, p[6]


def parse_teensy(line: str):
    """jp3141 Teensy reply '   Ticks, Cycles,  Frequency, FBUS, Total, Flt, Phase, 1Hz' -> (freq, cycles, flags)."""
    p = [x.strip() for x in line.strip().split(",")]
    if len(p) < 8 or not p[0].isdigit():
        return None
    try:
        cyc, f = int(p[1]), float(p[2])
    except ValueError:
        return None
    if not (55.0 < f < 65.0) or cyc < 50:
        return None
    return f, cyc, "OK"


def iso(sec: int) -> str:
    return dt.datetime.fromtimestamp(sec, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_sync() -> str:
    """Ask chrony what the clock is locked to."""
    try:
        out = subprocess.run(["chronyc", "-c", "tracking"], capture_output=True, text=True, timeout=5).stdout
        ref = out.split(",")[1] if out else ""
        leap = out.strip().split(",")[-1] if out else ""
        if leap.lower().startswith("not"):
            return "unsync"
        return "pps" if ref.upper().startswith("PPS") else "ntp"
    except Exception:
        return "unsync"


class DailyCSV:
    """Appends rows to <dir>/gridfreq_YYYY-MM-DD.csv (UTC day) and gzips days older than keep_plain."""

    def __init__(self, folder, keep_plain=2):
        self.folder, self.keep_plain, self.day, self.fh = folder, keep_plain, None, None
        os.makedirs(folder, exist_ok=True)

    def path(self, day):
        return os.path.join(self.folder, f"gridfreq_{day}.csv")

    def write(self, sec, f, cyc, flags, sync):
        day = iso(sec)[:10]
        if day != self.day:
            if self.fh:
                self.fh.close()
            p = self.path(day)
            new = not os.path.exists(p)
            self.fh = open(p, "a", buffering=1)
            if new:
                self.fh.write(HEADER)
            self.day = day
            self.compress_old()
        self.fh.write(f"{iso(sec)},{f:.6f},{cyc},{flags},{sync}\n")

    def compress_old(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        for fn in os.listdir(self.folder):
            if not (fn.startswith("gridfreq_") and fn.endswith(".csv")):
                continue
            try:
                d = dt.date.fromisoformat(fn[9:19])
            except ValueError:
                continue
            if (today - d).days >= self.keep_plain:
                src = os.path.join(self.folder, fn)
                with open(src, "rb") as a, gzip.open(src + ".gz", "wb") as b:
                    shutil.copyfileobj(a, b)
                os.remove(src)


def run(port, source, folder, baud):
    import serial  # python3-serial
    ser = serial.Serial(port, baudrate=baud, timeout=1.5)
    out = DailyCSV(folder)
    sync, sync_t = clock_sync(), time.time()
    last_sec = None
    print(f"logging {source} on {port} -> {folder}", flush=True)
    if source == "teensy":
        ser.write(b" \n")              # first request resets the Teensy's counters (header line follows)
        ser.readline(); ser.readline()
    while True:
        if source == "teensy":
            # ask right after each UTC second boundary; the reply covers the second that just ended
            now = time.time()
            time.sleep(1.0 - (now % 1.0) + 0.002)
            ser.write(b"\n")
        line = ser.readline().decode("ascii", "replace")
        now = time.time()
        rec = parse_pico(line) if source == "pico" else parse_teensy(line)
        if rec is None:
            continue
        if now - sync_t > 60:
            sync, sync_t = clock_sync(), now
        sec = int(round(now)) - 1      # the PPS edge that ended the interval is round(now); it started 1 s earlier
        if sec == last_sec:
            continue
        last_sec = sec
        f, cyc, flags = rec
        out.write(sec, f, cyc, flags, sync)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=("pico", "teensy"), default="pico")
    ap.add_argument("--port", default=None, help="default /dev/ttyACM0 (pico) or /dev/serial0 (teensy)")
    ap.add_argument("--dir", default=os.path.expanduser("~/gridfreq"))
    ap.add_argument("--baud", type=int, default=None)
    a = ap.parse_args(argv)
    port = a.port or ("/dev/ttyACM0" if a.source == "pico" else "/dev/serial0")
    baud = a.baud or (115200 if a.source == "pico" else 57600)
    while True:                        # survive unplugging: retry every 5 s
        try:
            run(port, a.source, a.dir, baud)
        except Exception as e:
            print("logger error:", e, file=sys.stderr, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
