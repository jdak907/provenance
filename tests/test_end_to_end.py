"""End to end on a small synthetic scene: the hidden listener must be found within 150 m."""
import json

from provenance_fx.cli import do_locate
from provenance_fx.simulate import build_scene


def test_two_event_search_finds_hidden_listener(tmp_path):
    data = tmp_path / "data"
    truth, sc = build_scene(str(data), seed=11, half_km=12.0, n_through=120, n_airport=30,
                            hours=(14.0, 17.0))
    res, summary = do_locate(str(data / "recording.wav"), str(data / "adsb.csv"), str(data / "dem.npz"),
                             sc["bbox"], sc["search_window_unix"], str(tmp_path / "out"),
                             truth_path=str(data / "truth_HIDDEN.json"), log=lambda *a: None)
    assert summary["error_m"] < 150, summary
    assert res.best["flight1"].startswith("c00001") and res.best["flight2"].startswith("c00002")
    assert (tmp_path / "out" / "report.md").exists()
    assert (tmp_path / "out" / "fig_map.png").exists()


def test_one_minute_known_time_search(tmp_path):
    data = tmp_path / "data"
    truth, sc = build_scene(str(data), seed=11, half_km=12.0, n_through=120, n_airport=30,
                            hours=(14.0, 17.0))
    res, summary = do_locate(str(data / "one_minute.wav"), str(data / "adsb.csv"), str(data / "dem.npz"),
                             sc["bbox"], sc["search_window_unix"], str(tmp_path / "out1"),
                             clip_start=sc["one_minute_start_unix"], max_events=1,
                             truth_path=str(data / "truth_HIDDEN.json"), log=lambda *a: None)
    assert summary["error_m"] < 150, summary
