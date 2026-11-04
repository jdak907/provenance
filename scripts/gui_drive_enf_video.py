"""Drive the ENF tab's US samples with headless Chromium and save gui_screenshots/enf_video_*.png.
Usage: python scripts/gui_drive_enf_us.py  (GUI must be running on 127.0.0.1:8765)"""
import os, time
from playwright.sync_api import sync_playwright
import importlib.util
spec = importlib.util.spec_from_file_location("g", os.path.join(os.path.dirname(__file__), "gui_drive_enf.py"))
OUT = os.path.join(os.path.dirname(__file__), "..", "gui_screenshots")
URL = "http://127.0.0.1:8765/"
CASES = [("vid_av", "01_av_agree_race_win"), ("vid_splice", "02_splice_partly_disagree"), ("vid_silent", "03_silent_picture_only"), ("vid_antiband", "04_antiband_abstain")]


def run_case(p, sid, name):
    p.evaluate("document.querySelector('#enfFileInfo').textContent='';document.querySelector('#enfStatus').textContent='';document.querySelector('#enfOut').innerHTML=''")
    p.click(f"#enfSamples .card[data-id='{sid}']")
    p.wait_for_function("document.querySelector('#enfFileInfo').textContent.includes(' s ·')", timeout=60000)
    time.sleep(1.0)
    if False:
        el = p.query_selector("#enfCov")
        el.scroll_into_view_if_needed(); time.sleep(0.3)
        el.screenshot(path=os.path.join(OUT, "enf_us_00_coverage.png"))
    t0 = time.time()
    p.click("#enfRun")
    p.wait_for_function("(s=>s.includes('done')||s.toLowerCase().includes('error'))(document.querySelector('#enfStatus').textContent)", timeout=900000)
    time.sleep(0.5)
    p.wait_for_selector("#enfOut .badge", timeout=60000)
    p.wait_for_function("[...document.querySelectorAll('#enfOut img')].every(i=>i.complete&&i.naturalWidth>0)", timeout=60000)
    time.sleep(0.5)
    p.screenshot(path=os.path.join(OUT, f"enf_video_{name}.png"), full_page=True)
    print(name, round(time.time() - t0), "s |", p.text_content("#enfStatus"), "|",
          (p.text_content("#enfOut") or "")[:700].replace("\n", " "), flush=True)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1500, "height": 1000})
    errs = []
    p.on("console", lambda m: m.type == "error" and errs.append(m.text))
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto(URL)
    p.click(".tab[data-tab='enf']")
    p.wait_for_selector("#enfSamples .card")
    for sid, name in CASES:
        run_case(p, sid, name)
    print("CONSOLE ERRORS:", errs)
    b.close()
