"""Real UK clips used in validation: path, approximate time window for the recording start, truth."""
import os
import numpy as np
from provenance_fx.enf.extract import EnfTrace, extract_enf, hum_scan, detect_enf
from provenance_fx.enf.media import load_raw
_DATA = __import__("os").environ.get("PROVENANCE_DATA", __import__("os").path.expanduser("~/provenance-data"))

LIVE = os.path.join(_DATA, "live_uk")
VOD = os.path.join(_DATA, "railcam_vod")
T_LIVE = 1793722634.7  # 2026-11-03T16:17:14Z capture start
# (key, path, nominal start time guess, +- window seconds, truth grid, note)
CLIPS = [
    ("heathrow_live", f"{LIVE}/rec_SgvpyjQX_HM.m4a", T_LIVE, 3600, "GB", "live capture, start known to ~1 min"),
    ("york_north_live", f"{LIVE}/rec_YzpJc0otTFs.m4a", T_LIVE, 3600, "GB", "live capture, stalled stream"),
    ("crewe_live", f"{LIVE}/rec_t65TCpcJOPQ.m4a", T_LIVE, 3600, "GB", "live capture, stalled stream"),
    ("sampler_live", f"{LIVE}/rec_ZC7HiaMkmlU.m4a", T_LIVE, 3600, "GB", "live capture, stalled stream"),
    ("york_south_live", f"{LIVE}/rec_4P2n_wCQAHo.m4a", T_LIVE, 3600, "GB", "inverter hum (not mains)"),
    ("ribblehead_vod", f"{VOD}/vod_vSOuVeHI2KY.m4a", 1746524196 + 300, 7200, "GB", "YouTube archive, release time +300 s"),
    ("sampler_vod", f"{VOD}/vod_dQze_bvWgaw.m4a", 1750877621 + 300, 7200, "GB", "YouTube archive"),
    ("epping_vod_a", f"{VOD}/vod_LNmS5Gd6gZQ.m4a", 1744875877 + 300, 7200, "GB", "YouTube archive"),
    ("epping_vod_b", f"{VOD}/vod_IoToHZ0orgI.m4a", 1746079751 + 300, 7200, "GB", "YouTube archive"),
    ("ongar_vod", f"{VOD}/vod_0_g4CrD3s6E.m4a", 1746270162 + 300, 7200, "GB", "YouTube archive"),
    ("crowcombe_vod", f"{VOD}/vod_8PW4EVgqL60.m4a", 1744107221 + 300, 7200, "GB", "YouTube archive"),
    ("bluebell_vod_a", f"{VOD}/vod_20GoQ8sRzdk.m4a", 1743855132 + 300, 7200, "GB", "YouTube archive"),
]
TRACES = os.path.join(os.path.dirname(__file__), "..", "validation_runs", "traces")


def trace(key, path, nominal=50):
    p = os.path.join(TRACES, f"{key}_{nominal}.npz")
    if os.path.exists(p):
        z = np.load(p, allow_pickle=True)
        tr = EnfTrace(t=z["t"], f=z["f"], snr_db=z["snr"], nominal=nominal, harmonics_used=list(z["h"]),
                      harmonic_snr_db={}, harmonic_corr={}, per_harmonic={}, frame_s=8.0, hop_s=1.0)
        return tr, z["det"].item(), z["scan"].item()
    sr, x, meta = load_raw(path)
    scan = hum_scan(x, sr)
    tr = extract_enf(x, sr, nominal=nominal)
    det = detect_enf(tr, scan)
    os.makedirs(TRACES, exist_ok=True)
    np.savez(p, t=tr.t, f=tr.f, snr=tr.snr_db, h=np.array(tr.harmonics_used), det=np.array(det, dtype=object),
             scan=np.array({k: v for k, v in scan.items() if k in ("nominal", "guess", "note")}, dtype=object))
    return tr, det, scan
