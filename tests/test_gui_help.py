"""The Help tab: present in the page, wired in app.js, and covering every topic it promises."""
import os
import re

STATIC = os.path.join(os.path.dirname(__file__), "..", "provenance_fx", "gui", "static")
SECTIONS = ["h-what", "h-start", "h-locate", "h-leak", "h-enf", "h-video", "h-race", "h-refs", "h-conf", "h-limits",
            "h-cli", "h-trouble"]


def _read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        return fh.read()


def test_help_tab_markup_and_wiring():
    html, js = _read("index.html"), _read("app.js")
    assert 'data-tab="help"' in html and 'id="tab-help"' in html
    # the four tabs keep their names
    for label in (">Acoustic Locate<", ">Acoustic Locate · Leak Check<", ">ENF · mains hum<", ">Help<"):
        assert label in html
    for sid in SECTIONS:
        assert f'id="{sid}"' in html, sid
        assert f'data-go="{sid}"' in html, sid
    assert "#tab-help" in js and "#helpToc a" in js


def test_help_numbers_match_the_code():
    """The thresholds quoted in the Help tab are the ones the race and matcher actually use."""
    from provenance_fx.enf import race, match
    html = _read("index.html")
    help_txt = html[html.index('id="tab-help"'):]
    assert race.DECISIVE == dict(r=0.80, dz=1.0, p=0.01) and "0.80 or more" in help_txt and "under 0.01" in help_txt
    assert race.LIKELY == dict(r=0.60, dz=0.5, p=0.5) and "0.60 or more" in help_txt and "under 0.5" in help_txt
    assert race.SINGLE_GRID_P == 0.05 and "under 0.05" in help_txt
    assert race.LOW_TRUST_DZ == 1.5 and "1.5 times" in help_txt
    assert race.MIN_DUR_S == 180 and "3 minutes" in help_txt
    assert match.MIN_RELIABLE_S == 120 and match.GOOD_S == 300
    assert not re.search(r"flyloc", html, re.I)
    from provenance_fx.enf import video
    assert video.MIN_SEG_S == 4 and "shorter than 4 seconds" in help_txt
    assert video.MIN_CLIP_S == 30 and "under 30 seconds" in help_txt
    assert video.BAND_SNR_MIN_DB == 6 and "at least 6 decibels" in help_txt
    assert video.READOUT_GRID_MS[0] == 4.0 and "from 4 milliseconds" in help_txt


def test_help_tab_served():
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from provenance_fx.gui.server import app
    r = TestClient(app).get("/")
    assert r.status_code == 200 and 'id="tab-help"' in r.text
