"""Optional part-time cross-check: public OpenWebRX receivers whose audio carries mains hum.

Tier B of live_enf_aggregator_design.md. A receiver is used like one ordinary listener through its
normal public web client interface (the same websocket its own web page uses):
  * part-time only: by default 10 minutes in each hour, one receiver at a time;
  * it never switches the receiver's band or profile; it listens to whatever the receiver is tuned to,
    at the offset you configure (default 0 = the profile's centre), in AM;
  * no audio is stored, only the hum frequency per second and the agreement score.
Ask the operator before running it continuously (design rule).

The audio clock of these streams runs about 0.1-0.2 % off, so the sample rate is fitted from packet
arrival times (a linear fit of samples vs wall clock); that leaves about +-1 s of network jitter, which
is why radios are a cross-check and never anchor the reference. Results go to
<SEISMIC_DIR>/US-WEST/sdr_crosscheck.jsonl: receiver, start, seconds, harmonic, r and lag against the
seismic consensus of the same seconds.

Config file (JSON):  {"minutes_per_hour": 10, "receivers": [{"host": "fullerton.w6mfb.com", "offset_hz": 0}]}
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import ssl
import struct
import time

import numpy as np

from .mseed import Segment
from . import seismic as S

log = logging.getLogger("seismic_sdr")

_IDX = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]
_STEP = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97,
         107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796,
         876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871,
         5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385,
         24623, 27086, 29794, 32767]


class Adpcm:
    """OpenWebRX's IMA-ADPCM variant with SYNC blocks (as in its receiver.js)."""

    def __init__(self):
        self.si, self.pred, self.step, self.phase, self.sync, self.sb, self.cnt = 0, 0, 7, 0, 0, bytearray(), 0

    def _nib(self, n):
        self.si = min(max(self.si + _IDX[n], 0), 88)
        d = self.step >> 3
        if n & 1:
            d += self.step >> 2
        if n & 2:
            d += self.step >> 1
        if n & 4:
            d += self.step
        if n & 8:
            d = -d
        self.pred = min(max(self.pred + d, -32768), 32767)
        self.step = _STEP[self.si]
        return self.pred

    def decode(self, data):
        out = []
        for b in data:
            if self.phase == 0:
                if b != b"SYNC"[self.sync]:
                    self.sync = 0
                else:
                    self.sync += 1
                if self.sync == 4:
                    self.sb = bytearray()
                    self.phase = 1
            elif self.phase == 1:
                self.sb.append(b)
                if len(self.sb) == 4:
                    self.si, self.pred = struct.unpack("<hh", bytes(self.sb))
                    self.step = _STEP[self.si]
                    self.cnt = 1000
                    self.phase = 2
            else:
                out.append(self._nib(b & 15))
                out.append(self._nib(b >> 4))
                self.cnt -= 1
                if self.cnt == 0:
                    self.sync = 0
                    self.phase = 0
        return out


async def listen(host, seconds, offset_hz=0, mod="am", bw=4000):
    """Audio (int16, nominal 12 kHz) and [(wall_time, sample_index)] from one OpenWebRX receiver."""
    import websockets
    ctx = ssl.create_default_context()
    async with websockets.connect(f"wss://{host}/ws/", ssl=ctx, max_size=None, open_timeout=20, ping_interval=None) as ws:
        await ws.send("SERVER DE CLIENT client=openwebrx.js type=receiver")
        await ws.send(json.dumps({"type": "connectionproperties", "params": {"output_rate": 12000, "hd_output_rate": 48000}}))
        cfg, comp, started, t_end = {}, "adpcm", False, None
        codec, chunks, stamps, nsamp = Adpcm(), [], [], 0
        while True:
            m = await asyncio.wait_for(ws.recv(), 30)
            if isinstance(m, str):
                if m.startswith("{"):
                    j = json.loads(m)
                    if j.get("type") == "config":
                        cfg.update(j["value"])
                        comp = cfg.get("audio_compression", comp)
                        if not started and "center_freq" in cfg:
                            # demodulator settings only; the receiver's band/profile is left as it is
                            await ws.send(json.dumps({"type": "dspcontrol", "params": {
                                "low_cut": -bw, "high_cut": bw, "offset_freq": offset_hz, "mod": mod, "squelch_level": -150}}))
                            await ws.send(json.dumps({"type": "dspcontrol", "action": "start"}))
                            started, t_end = True, time.time() + seconds
                continue
            if m[0] == 2 and started:
                blk = m[1:]
                s = codec.decode(blk) if comp == "adpcm" else np.frombuffer(blk, "<i2").tolist()
                stamps.append((time.time(), nsamp))
                chunks.append(np.asarray(s, np.int16))
                nsamp += len(s)
            if t_end and time.time() > t_end:
                break
    return (np.concatenate(chunks) if chunks else np.zeros(0, np.int16)), np.array(stamps, float)


def hum_track(x, stamps, fs_nom=12000.0, harmonics=(60, 120, 180, 240)):
    """Per-second grid frequency from receiver audio. Wall-clock times come from a linear fit of
    sample index -> arrival time (skipping the first 20 s burst). Returns (T, f, harmonic, snr)."""
    keep = stamps[:, 1] > fs_nom * 20
    if keep.sum() < 10:
        keep = np.ones(len(stamps), bool)
    A = np.polyfit(stamps[keep, 1], stamps[keep, 0], 1)
    fs_eff = 1.0 / A[0]
    t_first = np.polyval(A, 0)
    # decimate by 12 first (12 kHz -> about 1 kHz); the fitted rate carries through exactly
    from scipy.signal import decimate
    xd = decimate(decimate(x.astype(float), 4, ftype="fir"), 3, ftype="fir")
    seg = Segment("sdr", t_first, fs_eff / 12.0, xd)
    best = None
    for h in harmonics:
        T, F, Sn = S.track_segment(seg, harmonic=h // 60, half=0.4 * h / 60)
        if len(T) == 0:
            continue
        sc = float(np.median(Sn))
        if best is None or sc > best[3]:
            best = (T, F, h, sc)
    return best


async def crosscheck_once(rcv, collector, seconds=600):
    host = rcv["host"]
    t_start = time.time()
    x, stamps = await listen(host, seconds, rcv.get("offset_hz", 0))
    if len(x) < 12000 * 60:
        return dict(host=host, start=t_start, error="too little audio")
    T, F, h, snr = hum_track(x, stamps)
    del x                                   # no audio is kept
    a, b = int(T[0]), int(T[-1]) + 1
    ids = collector.gates["US-WEST"].trusted()
    if len(ids) < 2:
        return dict(host=host, start=t_start, harmonic=h, snr_db=round(snr, 1), error="fewer than 2 trusted stations")
    # stations' tracks for these seconds become complete a couple of minutes later
    await asyncio.sleep(90)
    collector.track_all()
    M = np.vstack([collector.tracks[i].get(a, b) for i in ids])
    with np.errstate(all="ignore"):
        cons = np.nanmedian(M, axis=0)
    y = np.full(b - a, np.nan)
    y[T - a] = F
    y = y - np.nanmedian(y) + np.nanmedian(cons)   # receivers carry a constant rate offset after the fit
    r, L = S.corr_lag(y, cons, max_lag=15)
    return dict(host=host, start=dt.datetime.fromtimestamp(t_start, dt.timezone.utc).isoformat(timespec="seconds"),
                seconds=b - a, harmonic=h, snr_db=round(snr, 1), r=None if not np.isfinite(r) else round(r, 3), lag_s=L,
                stations=ids)


async def run_schedule(config_path, collector, stop):
    cfg = json.load(open(config_path))
    rcvs = cfg.get("receivers", [])
    mins = float(cfg.get("minutes_per_hour", 10))
    if not rcvs:
        return
    out = os.path.join(S.SEISMIC_DIR, "US-WEST", "sdr_crosscheck.jsonl")
    k = 0
    while not stop.is_set():
        rcv = rcvs[k % len(rcvs)]
        k += 1
        try:
            res = await crosscheck_once(rcv, collector, seconds=mins * 60)
        except Exception as e:
            res = dict(host=rcv.get("host"), error=str(e))
        log.info("SDR cross-check: %s", res)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "a") as fh:
            fh.write(json.dumps(res) + "\n")
        try:
            await asyncio.wait_for(stop.wait(), max(60.0, 3600 - mins * 60))
        except asyncio.TimeoutError:
            pass
