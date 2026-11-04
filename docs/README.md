# Documentation

| File | What |
|---|---|
| `design.md` | Acoustic Locate architecture, assumptions and limits. |
| `video-notes.md` | Breakdown of the colsto video the Acoustic Locate method rebuilds. |
| `validation.md`, `validation_synthetic.md` | Acoustic Locate validation: the real reference recording and simulated scenes. |
| `reference_validation_RUN.md` | How to reproduce the real-data Acoustic Locate test. |
| `enf_research.md`, `enf_scope.md` | ENF literature review and scope. |
| `enf_validation.md` | ENF, grid race, fallback classifier, US and seismic validation, failures included. |
| `western_grid_sources.md`, `live_enf_sources.md`, `live_enf_aggregator_design.md` | Research on US Western grid frequency sources and the seismic collector design. |
| `seismic_reference_guide.md` | How to run `enf-rebuild` and `enf-collect`. |
| `home_logger_guide.md` | Optional home grid-frequency logger. |
| `validation_runs/*.json` | Summary numbers behind the validation pages. |
| `img/` | Screenshots used by the main README. |

These pages were written during development. Some mention files that are not in this repository: screenshots in `gui_screenshots/`, logs and `.npz` files in `validation_runs/`, the `reference_validation/` folder (ADS-B extract under ODbL, frames from a copyrighted video) and datasets under `$PROVENANCE_DATA`. They were left out because of size, local paths or licenses. See `../DATA_SOURCES.md` for how to fetch the data.
