"""Screenshots of the seismic reference in the ENF tab: gui_screenshots/enf_seismic_*.png.
Usage: python scripts/gui_drive_enf_seismic.py  (GUI must be running on 127.0.0.1:8765)"""
import os, time
from playwright.sync_api import sync_playwright
OUT = os.path.join(os.path.dirname(__file__), "..", "gui_screenshots")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1500, "height": 1000})
    errs = []
    p.on("console", lambda m: m.type == "error" and errs.append(m.text))
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8765/")
    p.click(".tab[data-tab='enf']")
    p.wait_for_selector("#enfSamples .card")
    p.click("#enfSamples .card[data-id='us_seis']")
    p.wait_for_function("document.querySelector('#enfFileInfo').textContent.includes(' s ·')", timeout=60000)
    time.sleep(1.0)
    assert p.is_checked("#enfSeisOnly"), "seismic-only tick not set by the sample"
    el = p.query_selector("#enfCov"); el.scroll_into_view_if_needed(); time.sleep(0.3)
    el.screenshot(path=os.path.join(OUT, "enf_seismic_00_coverage.png"))
    p.click("#enfRun")
    p.wait_for_function("(s=>s.includes('done')||s.toLowerCase().includes('error'))(document.querySelector('#enfStatus').textContent)", timeout=900000)
    p.wait_for_selector("#enfOut .badge", timeout=60000)
    p.wait_for_function("[...document.querySelectorAll('#enfOut img')].every(i=>i.complete&&i.naturalWidth>0)", timeout=60000)
    time.sleep(0.5)
    p.screenshot(path=os.path.join(OUT, "enf_seismic_01_race_seismic_alone_west_wins.png"), full_page=True)
    print(p.text_content("#enfStatus"), "|", (p.text_content("#enfOut") or "")[:900].replace("\n", " "))
    # second case: a clip against the file the live collector wrote today
    p.evaluate("document.querySelector('#enfFileInfo').textContent='';document.querySelector('#enfStatus').textContent='';document.querySelector('#enfOut').innerHTML=''")
    p.click("#enfSamples .card[data-id='us_live']")
    p.wait_for_function("document.querySelector('#enfFileInfo').textContent.includes(' s ·')", timeout=60000)
    time.sleep(1.0)
    p.click("#enfRun")
    p.wait_for_function("(s=>s.includes('done')||s.toLowerCase().includes('error'))(document.querySelector('#enfStatus').textContent)", timeout=900000)
    p.wait_for_selector("#enfOut .badge", timeout=60000)
    p.wait_for_function("[...document.querySelectorAll('#enfOut img')].every(i=>i.complete&&i.naturalWidth>0)", timeout=60000)
    time.sleep(0.5)
    p.screenshot(path=os.path.join(OUT, "enf_seismic_02_live_collector_today_west_wins.png"), full_page=True)
    print(p.text_content("#enfStatus"), "|", (p.text_content("#enfOut") or "")[:900].replace("\n", " "))
    print("CONSOLE ERRORS:", errs)
    b.close()
