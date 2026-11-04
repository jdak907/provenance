"""Build the SIMULATED video samples for the ENF tab (light flicker + optional hum) from real grid logs.

Every file is synthetic: a textured lamp-lit room, the lamp's 100/120 Hz flicker driven by a real 1 s grid log
(Zenodo WECC 2024 or NESO GB), sensor noise, H.264 (crf 23) and, where noted, an AAC audio track with mains hum
from the same log. Truth (start time, grid, camera) is stored beside each file as <name>.truth.json.
Writes to $PROVENANCE_DATA/video_samples (default ~/.local/share/provenance/video_samples)."""
import datetime as dt
import json
import os
import sys
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from provenance_fx.enf import reference as R  # noqa: E402
from provenance_fx.enf import us_refs as U  # noqa: E402
from provenance_fx.enf.video_sim import render_video  # noqa: E402
from provenance_fx.gui.enf_api import VIDEO  # noqa: E402


def seg(ref, t0, n):
    i0 = int(round(t0 - ref.t0))
    f = ref.f[i0:i0 + n].astype(float)
    ok = np.isfinite(f)
    if ok.mean() < 0.95:
        raise SystemExit(f"grid log has gaps at {t0}")
    return np.interp(np.arange(n), np.where(ok)[0], f[ok])


def utc(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp()


def main():
    os.makedirs(VIDEO, exist_ok=True)
    w = U.load("zenodo_wecc_2024")
    w = w.to_1s() if w.step != 1 else w
    gb = R.neso_month(2024, 9).to_1s()
    jobs = []
    t = utc("2024-05-12T18:00:00")
    f = seg(w, t, 420)
    jobs.append(("vid_wecc_av.mp4", f, dict(audio_f_1s=f, audio_snr_db=0, fps="30000/1001", readout_ms=25), t, "US-WEST"))
    other = seg(w, t + 11 * 3600, 420)
    spl = f.copy(); spl[180:] = other[180:]
    jobs.append(("vid_wecc_splice.mp4", f, dict(audio_f_1s=spl, audio_snr_db=0, fps="30000/1001", readout_ms=25), t, "US-WEST"))
    t2 = utc("2024-09-19T03:30:00")
    f2 = seg(w, t2, 420)
    jobs.append(("vid_wecc_silent.mp4", f2, dict(fps="30", readout_ms=20), t2, "US-WEST"))
    t3 = utc("2024-09-14T20:15:00")
    f3 = seg(gb, t3, 420)
    jobs.append(("vid_gb_global.mp4", f3, dict(audio_f_1s=f3, audio_snr_db=-3, fps="30000/1001", readout_ms=0), t3, "GB"))
    jobs.append(("vid_wecc_antiband.mp4", f, dict(audio_f_1s=f, audio_snr_db=0, fps="30000/1001", readout_ms=25,
                                                  exposure_s=1 / 120), t, "US-WEST"))
    for name, fg, kw, t0, grid in jobs:
        p = os.path.join(VIDEO, name)
        truth = render_video(p, fg, seconds=360, seed=zlib.crc32(name.encode()) % 1000, creation_time=t0, **kw)
        truth.update(true_start_utc=dt.datetime.fromtimestamp(t0, dt.timezone.utc).isoformat(), grid=grid,
                     simulated=True, audio_spliced_at_s=180 if "splice" in name else None)
        truth.pop("pans", None)
        json.dump(truth, open(p.replace(".mp4", ".truth.json"), "w"), indent=1, default=str)
        print("wrote", p, os.path.getsize(p) // 1024, "kB")


if __name__ == "__main__":
    main()
