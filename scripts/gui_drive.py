"""Drive the Provenance GUI end to end with headless Chromium and save screenshots.
Usage: python scripts/gui_drive.py demo|reference [--clean]"""
import sys, time, os
from playwright.sync_api import sync_playwright

which = sys.argv[1]; do_clean = "--clean" in sys.argv
OUT = os.path.join(os.path.dirname(__file__), "..", "gui_screenshots")
URL = "http://127.0.0.1:8765/"
def shot(p, name): p.screenshot(path=os.path.join(OUT, f"{which}_{name}.png")); print("shot", name, flush=True)

with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    p.on("console", lambda m: m.type == "error" and errs.append(m.text))
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto(URL); p.wait_for_selector("#samples .card")
    shot(p, "01_load")
    p.click(f"#samples .card >> nth={0 if which == 'demo' else 1}")
    p.wait_for_selector("#step-2:not(.hidden)", timeout=120000)
    p.wait_for_function("document.querySelector('#specBefore').complete && document.querySelector('#specBefore').naturalWidth>0", timeout=120000)
    if do_clean:
        p.fill("#hp", "40"); p.dispatch_event("#hp", "input")
        p.click("#applyClean")
        p.wait_for_function("document.querySelector('#cleanStatus').textContent.includes('applied')", timeout=300000)
        p.wait_for_function("document.querySelector('#specAfter').complete && document.querySelector('#specAfter').naturalWidth>0", timeout=120000)
        time.sleep(1); shot(p, "02_cleanup")
        p.click(".step[data-step='3']")
    else:
        time.sleep(1); shot(p, "02_cleanup")
        p.click("#skipClean")
    p.wait_for_selector("#step-3:not(.hidden)"); time.sleep(3); shot(p, "03_settings")
    p.click("#goRun"); time.sleep(8); shot(p, "04_run")
    t0 = time.time()
    while time.time() - t0 < 1500:
        st = p.text_content("#runState")
        if "error" in st: print("RUN ERROR", st); print(p.text_content("#log")[-3000:]); break
        if not p.is_hidden("#step-5"): break
        time.sleep(5)
    print("run secs", round(time.time() - t0))
    if not p.is_hidden("#step-5"):
        time.sleep(6); shot(p, "05_results")
        print("BEST:", p.text_content("#bestBox"))
        print("RANK:", p.text_content("#rankTbl tbody")[:600])
        p.click("#zoomE1"); time.sleep(3)
        p.locator("#specCanvas").screenshot(path=os.path.join(OUT, f"{which}_06_spectrogram_event1.png"))
        p.click("#rankTbl tbody tr >> nth=1"); time.sleep(3); shot(p, "07_rank2_selected")
        p.click("#rankTbl tbody tr >> nth=0"); time.sleep(1)
    p.click(".tab[data-tab='audit']"); p.click("#runAudit")
    p.wait_for_selector("#auditOut .lvl", timeout=600000)
    p.wait_for_function("document.querySelector('#auditSpec').complete && document.querySelector('#auditSpec').naturalWidth>0", timeout=120000)
    time.sleep(1); shot(p, "08_audit")
    print("AUDIT:", p.text_content("#auditOut")[:500])
    print("CONSOLE ERRORS:", errs)
    b.close()
