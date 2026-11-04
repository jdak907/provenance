"""Minimal miniSEED 2 reader (numpy only): enough for FDSN dataselect and SeedLink records.

Supports the encodings public seismic networks actually serve: Steim1, Steim2, int16, int32,
float32, float64; big- or little-endian headers; any power-of-two record length (blockette 1000).
Decoding is vectorised across all records of one layout, so a station-day (about 30,000 records)
decodes in a second or two. No obspy needed, which keeps the Raspberry Pi install small.
"""
from __future__ import annotations

import datetime as dt
import struct
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Record:
    net: str
    sta: str
    loc: str
    cha: str
    start: float          # UTC epoch seconds of the first sample (time correction applied)
    fs: float
    nsamp: int
    encoding: int
    big: bool
    reclen: int
    data_off: int
    raw: bytes = field(repr=False)

    @property
    def sid(self):
        return f"{self.net}.{self.sta}.{self.loc}.{self.cha}"


def _rate(factor, mult):
    if factor == 0:
        return 0.0
    r = float(factor) if factor > 0 else -1.0 / factor
    if mult > 0:
        r *= mult
    elif mult < 0:
        r /= -mult
    return r


def parse_header(buf: bytes, off: int = 0):
    """Parse one record header at buf[off:]; returns (Record, reclen) or (None, step)."""
    h = buf[off:off + 48]
    if len(h) < 48 or h[6:7] not in (b"D", b"R", b"Q", b"M"):
        return None, 128
    big = True
    yr = struct.unpack(">H", h[20:22])[0]
    if not 1900 < yr < 2200:
        big = False
    e = ">" if big else "<"
    year, doy, hh, mm, ss, _, frac = struct.unpack(e + "HHBBBBH", h[20:30])
    nsamp, factor, mult = struct.unpack(e + "Hhh", h[30:36])
    act, _io, _q, nblk = struct.unpack("BBBB", h[36:40])
    tcorr, data_off, blk = struct.unpack(e + "iHH", h[40:48])
    enc, reclen, usec = None, None, 0
    p, guard = blk, 0
    while p and guard < 8:
        btype, nxt = struct.unpack(e + "HH", buf[off + p:off + p + 4])
        if btype == 1000:
            enc, _wo, lexp = struct.unpack("BBB", buf[off + p + 4:off + p + 7])
            reclen = 1 << lexp
        elif btype == 1001:
            usec = struct.unpack("b", buf[off + p + 5:off + p + 6])[0]
        elif btype == 100:
            fs_override = struct.unpack(e + "f", buf[off + p + 4:off + p + 8])[0]
            factor, mult = 0, 0
            fs = float(fs_override)
        p, guard = nxt, guard + 1
    if reclen is None:
        return None, 128
    t = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=doy - 1, hours=hh, minutes=mm,
                                                                        seconds=ss, microseconds=frac * 100)
    start = t.timestamp() + usec * 1e-6
    if not (act & 0x02):
        start += tcorr * 1e-4
    fs = _rate(factor, mult) if (factor or mult) else locals().get("fs", 0.0)
    rec = Record(h[18:20].decode().strip(), h[8:13].decode().strip(), h[13:15].decode().strip(),
                 h[15:18].decode().strip(), start, fs, nsamp, enc, big, reclen, data_off,
                 bytes(buf[off:off + reclen]))
    return rec, reclen


def iter_records(buf: bytes):
    off, n = 0, len(buf)
    while off + 48 <= n:
        rec, step = parse_header(buf, off)
        if rec is not None and off + rec.reclen <= n:
            yield rec
        off += step


def _sext(v, bits):
    v = v & ((1 << bits) - 1)
    return v - ((v >> (bits - 1)) << bits)


def _steim(recs, version):
    """Decode a batch of Steim records with the same record length and data offset."""
    rl, do, big = recs[0].reclen, recs[0].data_off, recs[0].big
    nf = (rl - do) // 64
    raw = np.frombuffer(b"".join(r.raw[do:do + nf * 64] for r in recs), dtype=">u4" if big else "<u4")
    W = raw.reshape(len(recs), nf, 16).astype(np.int64)
    X0 = W[:, 0, 1].astype(np.int64)
    X0 = np.where(X0 >= 2 ** 31, X0 - 2 ** 32, X0)
    shifts = 30 - 2 * np.arange(16)
    codes = (W[:, :, 0:1] >> shifts) & 3                       # (R, F, 16)
    codes[:, :, 0] = 0
    codes[:, 0, 1] = 0
    codes[:, 0, 2] = 0
    out = np.zeros(W.shape + (7,), np.int64)
    cnt = np.zeros(W.shape, np.int64)
    c1 = codes == 1                                            # 4 x 8 bit
    for i in range(4):
        out[..., i] = np.where(c1, _sext(W >> (24 - 8 * i), 8), out[..., i])
    cnt[c1] = 4
    if version == 1:
        c2, c3 = codes == 2, codes == 3
        for i in range(2):
            out[..., i] = np.where(c2, _sext(W >> (16 - 16 * i), 16), out[..., i])
        cnt[c2] = 2
        out[..., 0] = np.where(c3, _sext(W, 32), out[..., 0])
        cnt[c3] = 1
    else:
        dn = (W >> 30) & 3
        lay = {(2, 1): (1, 30), (2, 2): (2, 15), (2, 3): (3, 10), (3, 0): (5, 6), (3, 1): (6, 5), (3, 2): (7, 4)}
        for (c, d), (k, b) in lay.items():
            m = (codes == c) & (dn == d)
            if not m.any():
                continue
            for i in range(k):
                out[..., i] = np.where(m, _sext(W >> (b * (k - 1 - i)), b), out[..., i])
            cnt[m] = k
    R = len(recs)
    valid = np.arange(7)[None, None, None, :] < cnt[..., None]
    flat = out.reshape(R, -1)
    vm = valid.reshape(R, -1)
    res = []
    for r in range(R):
        d = flat[r][vm[r]]
        n = recs[r].nsamp
        if n == 0 or len(d) == 0:
            res.append(np.zeros(0, np.int64))
            continue
        d = d[:n].copy()
        d[0] = X0[r]
        res.append(np.cumsum(d))
    return res


def decode(recs):
    """Decode a list of Records -> list of numpy arrays (same order)."""
    out = [None] * len(recs)
    groups = {}
    for i, r in enumerate(recs):
        groups.setdefault((r.encoding, r.reclen, r.data_off, r.big), []).append(i)
    for (enc, rl, do, big), idx in groups.items():
        rs = [recs[i] for i in idx]
        if enc in (10, 11):
            vals = _steim(rs, 1 if enc == 10 else 2)
        else:
            dtp = {1: "i2", 3: "i4", 4: "f4", 5: "f8"}.get(enc)
            if dtp is None:
                vals = [np.zeros(0) for _ in rs]
            else:
                e = ">" if big else "<"
                vals = [np.frombuffer(r.raw[do:do + r.nsamp * np.dtype(dtp).itemsize], dtype=e + dtp).astype(float)
                        for r in rs]
        for i, v in zip(idx, vals):
            out[i] = v
    return out


@dataclass
class Segment:
    sid: str
    start: float
    fs: float
    data: np.ndarray

    @property
    def end(self):
        return self.start + len(self.data) / self.fs


def to_segments(recs, tol=0.5):
    """Group records by channel, sort, decode and join contiguous ones (gap under tol samples)."""
    by = {}
    for r in recs:
        if r.fs > 0 and r.nsamp > 0:
            by.setdefault(r.sid, []).append(r)
    segs = []
    for sid, rs in by.items():
        rs.sort(key=lambda r: r.start)
        # drop duplicates (same start) that SeedLink reconnects or overlapping requests produce
        uniq, last = [], None
        for r in rs:
            if last is not None and abs(r.start - last) < 0.5 / r.fs:
                continue
            uniq.append(r)
            last = r.start
        vals = decode(uniq)
        cur, parts = None, []
        for r, v in zip(uniq, vals):
            if cur is not None and abs(r.start - (cur[0] + cur[2] / cur[1])) <= tol / r.fs and r.fs == cur[1]:
                parts.append(v)
                cur[2] += len(v)
            elif cur is not None and r.start < cur[0] + cur[2] / cur[1] - tol / r.fs:
                # overlap: keep only the new samples beyond the current end
                skip = int(round((cur[0] + cur[2] / cur[1] - r.start) * r.fs))
                if skip < len(v):
                    parts.append(v[skip:])
                    cur[2] += len(v) - skip
            else:
                if cur is not None:
                    segs.append(Segment(sid, cur[0], cur[1], np.concatenate(parts).astype(float)))
                cur, parts = [r.start, r.fs, len(v)], [v]
        if cur is not None:
            segs.append(Segment(sid, cur[0], cur[1], np.concatenate(parts).astype(float)))
    return segs


def read_segments(buf: bytes):
    return to_segments(list(iter_records(buf)))
