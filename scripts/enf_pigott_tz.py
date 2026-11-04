"""Infer the clock offset of Pigott's Phoenix log (local Pi time) from WECC's daily cycle.

There is no concurrent public WECC log for 2022-23, so the offset is inferred, not proven:
1) hour offset: the average frequency vs time of day (10-min bins) of Pigott's log, read on its own
   clock, is circularly cross-correlated with the same profile of the 2024 Zenodo WECC log in UTC
   (same months, Feb..Oct, both years). Load cycles follow local time, so the daily shape repeats.
2) sub-minute check: WECC frequency has a fixed pattern locked to each clock minute (start-of-minute dip,
   Hartmann et al. 2025) and to each hour (schedule changes at :00). The best second-of-hour alignment
   between the two logs shows whether Pigott's clock is right to within seconds (NTP), modulo whole hours.
Writes validation_runs/enf_pigott_tz.json and gui_screenshots/enf_us_pigott_tz.png.
"""
import datetime as dt
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from provenance_fx.enf import us_refs as U  # noqa: E402

MONTHS = range(2, 11)


def series(ref, local_shift_h=0.0):
    """(seconds-of-day, seconds-of-hour, month, f) for finite samples; time = ref time + shift."""
    r = ref.to_1s() if ref.step == 1 else ref
    t = r.t0 + np.arange(len(r.f)) * r.step + local_shift_h * 3600
    ok = np.isfinite(r.f)
    t, f = t[ok], r.f[ok].astype(float)
    mon = (t.astype("datetime64[s]").astype("datetime64[M]").astype(int) % 12) + 1
    keep = np.isin(mon, list(MONTHS))
    t, f = t[keep], f[keep]
    return t % 86400, t % 3600, f


def prof(sec, f, period, nb):
    b = (sec / period * nb).astype(int) % nb
    s = np.bincount(b, weights=f - np.mean(f), minlength=nb)
    c = np.bincount(b, minlength=nb)
    return s / np.maximum(c, 1)


def main():
    zw = U.load("zenodo_wecc_2024")
    pg = U.load("pigott_phx_2022", tz_shift_h=-U.PIGOTT_TZ_H)   # raw local clock, no offset applied
    zs, zh, zf = series(zw)
    ps, ph, pf = series(pg)
    NB = 144
    a = prof(zs, zf, 86400, NB); b = prof(ps, pf, 86400, NB)
    a = (a - a.mean()) / a.std(); b = (b - b.mean()) / b.std()
    cc = np.array([np.mean(a * np.roll(b, k)) for k in range(NB)])   # roll Pigott local -> UTC by k bins
    k = int(np.argmax(cc))
    shift_h = (k * 24 / NB + 12) % 24 - 12        # UTC = local + shift_h
    top = sorted(((round(float(cc[i]), 3), round(((i * 24 / NB + 12) % 24) - 12, 2)) for i in range(NB)), reverse=True)[:5]
    # sub-minute: profile over the hour at 5 s bins; find best seconds shift (mod 1 h)
    NH = 720
    ah = prof(zh, zf, 3600, NH); bh = prof(ph - 2.5, pf, 3600, NH)   # Pigott values are 5 s means, centred
    ah = (ah - ah.mean()) / ah.std(); bh = (bh - bh.mean()) / bh.std()
    cch = np.array([np.mean(ah * np.roll(bh, j)) for j in range(NH)])
    j = int(np.argmax(cch)); sec_shift = ((j * 5 + 1800) % 3600) - 1800
    # minute pattern alone (mod 60 s)
    am = prof(zh % 60, zf, 60, 12); bm = prof((ph - 2.5) % 60, pf, 60, 12)
    am = (am - am.mean()) / am.std(); bm = (bm - bm.mean()) / bm.std()
    ccm = np.array([np.mean(am * np.roll(bm, j)) for j in range(12)])
    res = dict(assumed_tz_h=U.PIGOTT_TZ_H, inferred_local_to_utc_h=round(float(shift_h), 2),
               implied_utc_offset_h=round(-float(shift_h), 2), daily_profile_corr=round(float(cc[k]), 3), top5=top,
               corr_at_assumed=round(float(cc[int(round(-U.PIGOTT_TZ_H * NB / 24)) % NB]), 3),
               corr_at_utc=round(float(cc[0]), 3),
               hour_pattern_best_shift_s=int(sec_shift), hour_pattern_corr=round(float(cch[j]), 3),
               hour_pattern_corr_at_0=round(float(cch[0]), 3),
               minute_pattern_corr_by_5s_shift=[round(float(v), 3) for v in ccm])
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(ROOT, "validation_runs", "enf_pigott_tz.json"), "w"), indent=1)
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(15, 3.8))
    x = np.arange(NB) * 24 / NB
    ax[0].plot(x, a, label="Zenodo 2024, UTC"); ax[0].plot(x, np.roll(b, k), label=f"Pigott 2022, local clock {shift_h:+.1f} h")
    ax[0].plot(x, b, alpha=.4, lw=.8, label="Pigott, local clock as logged"); ax[0].set_xlabel("hour of day (UTC)"); ax[0].legend(fontsize=7)
    ax[0].set_title("Daily frequency cycle, Feb-Oct (z-scored)")
    ax[1].plot(((np.arange(NB) * 24 / NB + 12) % 24) - 12, cc, ".")
    ax[1].axvline(-U.PIGOTT_TZ_H, color="r", ls="--", label="assumed +7 h (MST)"); ax[1].legend(fontsize=7)
    ax[1].set_xlabel("hours added to Pigott's clock"); ax[1].set_title("daily-profile correlation")
    xs = np.arange(NH) * 5 / 60
    ax[2].plot(xs, ah, lw=.7, label="Zenodo 2024"); ax[2].plot(xs, bh, lw=.7, label="Pigott (clock as logged)")
    ax[2].set_xlabel("minute of hour"); ax[2].set_title("pattern locked to the hour (5 s bins)"); ax[2].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(os.path.join(ROOT, "gui_screenshots", "enf_us_pigott_tz.png"), dpi=90)


if __name__ == "__main__":
    main()
