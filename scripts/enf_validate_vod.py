"""Blind ENF dating of archived UK live streams (Railcam UK VODs) against NESO 1 s GB data.

Ground truth: YouTube's release_timestamp (actual live start, UTC) + the section offset we
downloaded. Archived live streams can have small gaps, so truth is good to ~seconds-minutes.
Search window: +-1 day around the truth (48 h of NESO data), recording start unknown to the matcher.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provenance_fx.enf import detect_enf, extract_enf, hum_scan, load_raw  # noqa: E402
from provenance_fx.enf import gridid  # noqa: E402
from provenance_fx.enf import match as M  # noqa: E402
from provenance_fx.enf import reference as R  # noqa: E402
_DATA = __import__("os").environ.get("PROVENANCE_DATA", __import__("os").path.expanduser("~/provenance-data"))

D = os.path.join(_DATA, "railcam_vod")
META = os.path.join(_DATA, "live_uk/vod_meta.txt")
OFFSET = 300.0


def main():
    meta = {}
    for ln in open(META):
        p = ln.strip().split("|")
        if len(p) >= 5 and p[1] not in ("NA", "None"):
            meta[p[0]] = dict(release=float(p[1]), duration=p[3], title=p[4])
    out = []
    for fn in sorted(os.listdir(D)):
        if not fn.startswith("vod_") or fn.endswith(".part") or fn.endswith(".txt"):
            continue
        vid = fn[4:].rsplit(".", 1)[0]
        if vid not in meta:
            continue
        truth = meta[vid]["release"] + OFFSET
        sr, x, info = load_raw(os.path.join(D, fn))
        scan = hum_scan(x, sr)
        try:
            tr = extract_enf(x, sr, nominal=50)
        except ValueError as e:
            row = dict(id=vid, title=meta[vid]["title"], url=f"https://www.youtube.com/watch?v={vid}",
                       truth=R.Reference(truth, 1, [], "").label_time(truth), error=str(e))
            print(json.dumps(row), flush=True); out.append(row)
            continue
        det = detect_enf(tr)
        ref = R.gb_reference(truth - 86400, truth + 86400 + len(x) / sr + 60, log=print)
        try:
            m = M.match(tr, ref)
        except ValueError as e:
            row = dict(id=vid, title=meta[vid]["title"], truth=ref.label_time(truth), error=str(e))
            print(json.dumps(row), flush=True); out.append(row)
            continue
        c = M.continuity(tr, ref, m)
        g = gridid.classify(tr, 50)
        row = dict(id=vid, title=meta[vid]["title"], url=f"https://www.youtube.com/watch?v={vid}",
                   truth=R.Reference(0, 1, [], "").label_time(truth) if False else ref.label_time(truth),
                   duration=round(len(x) / sr), hum=scan["note"], detect=det["verdict"], flat=det["flat"],
                   harmonics=tr.harmonics_used, est=m["start_label"], err_s=round(m["start_time"] - truth, 1),
                   ncc=m["ncc"], second=m["second_ncc"], label=m["label"], p_false=m["p_false"],
                   rmse_mhz=m["rmse_mhz"], offset_mhz=m["offset_mhz"], continuity=c["verdict"],
                   grid=g.get("best"), grid_p=round(g["probs"].get(g.get("best"), 0), 2) if g.get("probs") else None)
        print(json.dumps(row), flush=True)
        out.append(row)
    json.dump(out, open("validation_runs/enf_vod.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
