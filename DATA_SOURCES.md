# Data sources, licenses and how to fetch them

Provenance bundles **no third-party dataset**. Reference data is either fetched on demand from a public, no-login service (and cached in `~/.cache/provenance/`), or downloaded by you into `$PROVENANCE_DATA` (default `~/provenance-data`). Check each license yourself before you publish results; items marked [VERIFY] were not confirmed. The README [References](README.md#references) section gives the full citation, with DOI or link, for every source here.

## What *is* in this repository

| File | What | Origin and license |
|---|---|---|
| `provenance_fx/enf/grid_profiles.json` | Coefficients of the fallback grid classifier (plain JSON) | Produced by this project from the sources below. Contains summary model weights only, no raw data. MIT with the code. |
| `scripts/legacy_grid_profiles_v1.json` | Older classifier coefficients, kept for comparison | Same as above. |
| `tests/data/sl_sample.mseed` (40 KB) | A short miniSEED record from station NN.HYDE, used to test the miniSEED reader | Nevada Seismological Laboratory network NN, DOI 10.7914/SN/NN, distributed by EarthScope. Open data; cite the network DOI. [VERIFY] the exact license wording for redistribution. |
| `tests/data/sl_sample_obspy.npz` | The same record decoded by ObsPy, as the test's expected answer | Derived from the record above. |
| `provenance_fx/gui/static/vendor/leaflet.*` | Leaflet map library | BSD 2-Clause, © Vladimir Agafonkin and contributors (https://leafletjs.com). |
| `docs/validation_runs/*.json`, `docs/img/*.png` | Validation summaries and screenshots | Produced by this project. Screenshots show map tiles © Esri and © OpenStreetMap contributors. |

## Fetched automatically (no login, cached in `~/.cache/provenance/`)

| Source | Used for | License and attribution | Endpoint |
|---|---|---|---|
| **NESO System Frequency Data** (Great Britain, 1 s, 2014 → latest published month) | GB ENF reference | NESO Open Data Licence. Attribution: "Supported by National Energy SO Open Data". | https://www.neso.energy/data-portal/system-frequency-data |
| **Elexon BMRS FREQ** (GB, 15 s, recent days) | Recent GB reference | BMRS data license: https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/ | https://data.elexon.co.uk/bmrs/api/v1/datasets/FREQ |
| **Energy-Charts** (Fraunhofer ISE, Freiburg meter, Continental Europe, 1 s, from 2022-05) | CE reference | CC BY 4.0 [VERIFY]. Credit "Energy-Charts, Fraunhofer ISE". | https://api.energy-charts.info/frequency |
| **Fingrid open data** monthly 7z archives (Nordic, 10 Hz, from 2024-01, published about a month late) | Nordic reference (needs `py7zr`) | Creative Commons Attribution, as stated on https://data.fingrid.fi/en/datasets/339 (version 4.0 [VERIFY]). Credit "Fingrid". | https://data.fingrid.fi/files/339/ |
| **EarthScope / SAGE FDSN dataselect**, plus SCEDC and NCEDC data centres | Seismic US West rebuild (`enf-rebuild`) | Open seismic data; cite each network's DOI (list below). EarthScope announced that archive downloads need an account from 2026-12-15 [VERIFY]. | https://service.earthscope.org, https://service.scedc.caltech.edu, https://service.ncedc.org |
| **EarthScope SeedLink** (real time, over wss port 443) | Live collector (`enf-collect`) | As above. | wss://rtserve.earthscope.org/seedlink |
| **AWS Terrain Tiles** (Terrarium, zoom 12, about 30 m) | Terrain for Acoustic Locate (`--dem auto`) | AWS Open Data; tiles combine several public sources (SRTM, NED and others) with their own attribution terms (see the registry page) [VERIFY]. | https://registry.opendata.aws/terrain-tiles/ |
| **Map tiles**: Esri World Imagery / dark basemap, OpenStreetMap | GUI map background only (loaded by your browser) | © Esri and its data providers; © OpenStreetMap contributors (ODbL). Follow each tile provider's usage policy. | https://server.arcgisonline.com, https://tile.openstreetmap.org |

### Seismic networks used for the US West reference

Cite these when you publish results built from `enf-rebuild` or `enf-collect` (from `provenance_fx/enf/seismic.py: NETWORK_DOIS`):

| Network | Citation |
|---|---|
| PB | Plate Boundary Observatory Borehole Seismic Network (operated by UNAVCO, now EarthScope); the FDSN page lists no DOI |
| UW | doi:10.7914/SN/UW, Pacific Northwest Seismic Network, University of Washington |
| NN | doi:10.7914/SN/NN, Nevada Seismological Laboratory |
| MB | doi:10.7914/SN/MB, Montana Regional Seismic Network |
| UI | North Idaho Seismic Network, University of Idaho; the FDSN page lists no DOI |
| UO | doi:10.7914/SN/UO, University of Oregon |
| TX | doi:10.7914/SN/TX, Texas Seismological Network (TexNet) |
| NX | Nanometrics Research Network, DOI 10.7914/SN/NX |

**Excluded on purpose:** Raspberry Shake (network AM). Its license forbids redistribution and its real-time feed is paid, so the code refuses AM stations (`EXCLUDED_NETWORKS`).

## Downloaded by you into `$PROVENANCE_DATA`

None of these are redistributed here. Download them yourself, respecting each license, into the layout shown. Everything is optional: the tool runs without them, and the related GUI sample cards show as unavailable.

```
$PROVENANCE_DATA/                      (default ~/provenance-data)
├── ENF-WHU-Dataset/ENF-WHU-Dataset/   H0/ H1/ H1_ref/ H1_ref_one_day/
├── osf_pgfdb/                         GB01/ FR01/ PL01/ IT01/ SE01/ US_UT01/ US_TX01/ US_TX02/ US_FL01/ ...
├── us/
│   ├── wi_member.bin | zenodo_west.csv[.gz]    Zenodo Western Interconnection 2024
│   ├── ei_member.bin | zenodo_east.csv[.gz]    Zenodo Eastern 2023
│   ├── pigott_60Hz.log.gz                      Pigott Phoenix 2022
│   ├── nategriff/20*.csv                       nate-griff FNET scrape 2026
│   └── samples/                                your own US test clips
├── wecc_samples/                      validation truth files written by the scripts
└── live_uk/                           your own captured test clips
```

| Dataset | License | Where to get it | Then |
|---|---|---|---|
| **ENF-WHU** (Hua et al.; 130 real recordings plus mains references, Wuhan, 50 Hz) | MIT | https://github.com/ghua-ac/ENF-WHU-Dataset | Clone into `ENF-WHU-Dataset/`. Used by `scripts/enf_validate_whu.py` and two GUI samples. |
| **Power grid frequency database** (Jumar et al., OSF by5hu; 1 s, fixed weeks, 2019 and 2023) | CC BY 4.0 [VERIFY] | https://osf.io/by5hu/ (see also https://power-grid-frequency.org/archive-database/) | Unpack each site to `osf_pgfdb/<CODE>/<CODE>.csv`. Override with `PROVENANCE_OSF_DIR`. |
| **Zenodo, De Din, Carta and Hartmann, Data for "Cyber-Physical Systems on the Megawatt Scale"** (US West 2024-01-16 → 2024-11-18 and US East 2023, 1 s, GPS-timed) | CC BY 4.0 | https://doi.org/10.5281/zenodo.17366693 (510 MB zip). A separate, later record from the same authors is https://doi.org/10.5281/zenodo.21997337 | Extract the Western CSV (`Time;f60;QI`) to `us/zenodo_west.csv` (or `.csv.gz`), the Eastern one to `us/zenodo_east.csv`, then build the caches (below). Rows with QI=2 are filled-in gaps and are dropped. |
| **jp3141 60Hz log** (Phoenix AZ, 2022-02-14 → 2023-02-23, 5 s, clock offset inferred as UTC-7) | MIT (repository license) | https://github.com/jp3141/60Hz; data file on OSF https://osf.io/cq285 (`60Hz.log.gz`) | Save as `us/pigott_60Hz.log.gz`. |
| **nate-griff FNET gauge scrape** (US West, East, Texas, Quebec, 2026-03-20 → 2026-05-12, about 2 s, low trust) | no license stated in the repository; derived from the public FNET/GridEye display (University of Tennessee) whose terms also apply [VERIFY] | https://github.com/nate-griff/enf | Copy the daily CSVs to `us/nategriff/`. |
| **adsb.lol globe_history** (daily ADS-B archive, about 4 GB per day) | ODbL 1.0 (share-alike; credit "adsb.lol contributors") | https://github.com/adsblol/globe_history_2026/releases | `cat v2026.09.08-planes-readsb-prod-0.tar.* \| python -m provenance_fx.readsb_hist --bbox ... --out adsb.csv`. The GUI can also fetch a day for you. Filtered extracts are a derived database under ODbL: share them only under the same license. |

Build the US caches once after downloading:

```bash
python -c "from provenance_fx.enf import us_refs; us_refs.build_all()"
```

## Used in validation only, not redistributed

These were used to test the tool. They are copyrighted media and are **not** included; the validation docs list them by URL so results can be checked.

- colsto, reference recording "Unknown location - raw audio", https://youtu.be/4CxVxuMVkMc, and the explainer video https://www.youtube.com/watch?v=UytYrhYLOKI (Acoustic Locate real-data test; see `docs/validation.md`).
- Public UK live-stream and archive audio (Heathrow live cam, Railcam UK streams); URLs are in `docs/enf_validation.md` and `docs/validation_runs/enf_vod.json`.

## Free sources that need registration (listed, not used)

ENTSO-E Transparency API key, Fingrid open-data API key (the monthly archives above need none), gridradar.net API, FNET/GridEye data requests.

## Not scraped

KGRID and similar live dashboards are deliberately not scraped.

## Video test data (downloaded by you, not bundled)

| Source | Used for | License and attribution | Where |
|---|---|---|---|
| **ENF Moving Video Database** (Fernández-Menduiña and Pérez-González, University of Vigo, 2020). 9 phone videos (MP4, 1.2 to 3.5 GB) and 9 mains recordings (WAV, 1 kHz, 15 min), Continental Europe 50 Hz, 2019 | Real-footage check of video light-flicker ENF (`docs/enf_validation.md`, section 15) | CC BY 4.0. Cite: Fernández-Menduiña, S., and Pérez-González, F. (2020). ENF Moving Video Database. Zenodo. doi:10.5281/zenodo.3549379 | https://zenodo.org/records/3549379 (put files in `$PROVENANCE_DATA/zenodo_enf_video/`) |
| Simulated video samples for the ENF tab | GUI samples | Made by `scripts/enf_make_video_samples.py` from the grid logs above (Zenodo WECC 2024, NESO). Not bundled; regenerate locally. | `$PROVENANCE_DATA/video_samples/` |

Not used: IEEE DataPort rolling-shutter video sets (login required) and Zenodo 10.5281/zenodo.3407735 (files restricted).
