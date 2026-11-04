"""Drive the ENF tab with headless Chromium and save gui_screenshots/enf_*.png.
Usage: python scripts/gui_drive_enf.py"""
import os
import time

from playwright.sync_api import sync_playwright
_DATA = __import__("os").environ.get("PROVENANCE_DATA", __import__("os").path.expanduser("~/provenance-data"))

OUT = os.path.join(os.path.dirname(__file__), "..", "gui_screenshots")
URL = "http://127.0.0.1:8765/"
CASES = [("whu120", "01_whu120_strong_match"), ("lhr", "02_heathrow_live_gb"),
         ("ribble", "03_ribblehead_archive_neso"), ("york", "04_york_video_inverter_hum"),
         ("whu_h0", "05_no_enf_control")]


GRID_CASES = [("race_sampler", "grid_01_race_sampler_archive_gb_wins"), ("race_lhr", "grid_02_race_heathrow_live_gb"),
              ("york", "grid_03_race_inverter_hum_abstains"), ("lhr", "grid_04_no_time_statistical_fallback")]


def run_case(p, sid, name, errs, clear_window=False):
    p.evaluate("document.querySelector('#enfFileInfo').textContent='';document.querySelector('#enfStatus').textContent='';document.querySelector('#enfOut').innerHTML=''")
    p.click(f"#enfSamples .card[data-id='{sid}']")
    p.wait_for_function("document.querySelector('#enfFileInfo').textContent.includes(' s ·')", timeout=60000)
    if clear_window:  # time unknown: no window, reference none -> statistical fallback only
        p.check("input[name=enfRef][value=none]")
        p.fill("#enfStart", ""); p.fill("#enfEnd", "")
    p.click("#enfRun")
    p.wait_for_function("(s=>s.includes('done')||s.toLowerCase().includes('error'))(document.querySelector('#enfStatus').textContent)", timeout=900000)
    time.sleep(0.5)
    p.wait_for_selector("#enfOut .badge", timeout=60000)
    p.wait_for_function("[...document.querySelectorAll('#enfOut img')].every(i=>i.complete&&i.naturalWidth>0)", timeout=60000)
    time.sleep(0.5)
    p.screenshot(path=os.path.join(OUT, f"enf_{name}.png"), full_page=True)
    print(name, "|", p.text_content("#enfStatus"), "|", (p.text_content("#enfOut") or "")[:300].replace("\n", " "), flush=True)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1500, "height": 1000})
    errs = []
    p.on("console", lambda m: m.type == "error" and errs.append(m.text))
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto(URL)
    p.click(".tab[data-tab='enf']")
    p.wait_for_selector("#enfSamples .card")
    p.screenshot(path=os.path.join(OUT, "enf_00_tab.png"))
    if not os.environ.get("GRID_ONLY"):
        for sid, name in CASES:
            run_case(p, sid, name, errs)
    for sid, name in GRID_CASES:
        run_case(p, sid, name, errs, clear_window=name.endswith("fallback"))
        if name.startswith("grid_01"):  # close-up of the race section
            el = p.query_selector("#enfOut h3:nth-of-type(1)")
            box = p.evaluate("(()=>{const h=[...document.querySelectorAll('#enfOut h3')].find(x=>x.textContent.startsWith('Which grid'));const r=h.getBoundingClientRect();const img=[...document.querySelectorAll('#enfOut img')].find(i=>i.src.includes('/race.png'));const b=img.getBoundingClientRect();return {x:r.x-10,y:r.y+window.scrollY-10,w:Math.max(r.width,b.width)+20,h:b.bottom-r.y+20}})()")
            p.screenshot(path=os.path.join(OUT, "enf_grid_00_race_closeup.png"), full_page=True,
                         clip=dict(x=box["x"], y=box["y"], width=box["w"], height=box["h"]))
    # upload path: a video file through the file input (same handler as drag-drop)
    p.set_input_files("#enfFile", os.path.join(_DATA, "live_uk/video_4P2n_wCQAHo.mp4"))
    p.wait_for_function("document.querySelector('#enfFileInfo').textContent.includes('VIDEO')", timeout=120000)
    p.screenshot(path=os.path.join(OUT, "enf_06_video_upload.png"))
    print("upload:", p.text_content("#enfFileInfo"))
    print("CONSOLE ERRORS:", errs)
    b.close()
