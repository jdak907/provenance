# Public Western US grid-frequency records (WECC), plus logger designs

Research date: Tuesday Nov 3, 2026 (America/Los_Angeles, PST).
Scope: public, real, measured WECC frequency data at 1 second or finer (sub-minute accepted), for use as an ENF reference.
Method: searched GitHub, Zenodo, OSF, Kaggle, Hugging Face, Figshare, IEEE DataPort, lab sites, ISO and utility pages, Reddit, and time-nuts. I downloaded free samples and checked them.
Rules followed: nothing sent, nothing posted, no sign-ups, no logins, no credentials used. No code in the tool was changed.
Items marked [VERIFY] are unconfirmed.

## Short answer

Is there a free, continuous, historical Western record? **Yes, with limits.**

- **What exists:** a free 1-second WECC record of about 10 months, from Jan 16 to Nov 18, 2024. It is the Zenodo dataset by E. De Din, D. Carta and C. Hartmann (doi 10.5281/zenodo.17366693), which supplements the paper by C. Hartmann et al. (arXiv:2510.09862; co-authors include D. Witthaut). It is real measured data, CC BY 4.0, and needs no login.
- **What doesn't exist:** a public Western archive that is still updating. FNET/GridEye hid its data in 2018, and access now goes through the lab on request. PNNL's national PMU set is under an NDA. CAISO data is limited to RC West members. WECC publishes 1-minute summaries only.
- **Other spans:** apart from that 2024 year, coverage is patchy:
  - Phoenix, 2022: 5-second data, about one year.
  - Salt Lake City, May 2019: one week.
  - Berkeley, Oct–Dec 2015: µPMU phase data at 120 Hz.
  - Seattle, June 2023: a few days.
  - nate-griff, Mar 20 – May 12, 2026: 54 days digitised from the FNET gauge images.
  For anything after May 2026, you have to log it yourself.

## Ranked findings

### 1. Zenodo: De Din, Carta and Hartmann, data for "Cyber-Physical Systems on the Megawatt Scale", US Western Interconnection (best)
- Links:
  - https://zenodo.org/records/17366693 (v1, Oct 2025). The file is inside "Grid Frequency Data.zip", which is 510 MB compressed.
  - https://doi.org/10.5281/zenodo.21997337 (Aug 2026 version). The same Western CSV sits inside an 8.7 GB zip.
- Who: dataset creators E. De Din, D. Carta and C. Hartmann; the companion paper has 12 authors, including D. Witthaut. Affiliations [VERIFY].
  - Papers: arXiv 2510.09862, and Nature Energy 2026, "One-minute frequency disturbances from unintended synchronization in cyber–physical power systems".
- Recorder [VERIFY, not confirmed from the record]: KIT Electrical Data Recorder (GPS-timed point-on-wave), filtered zero-crossing method, distribution-level outlet.
- Location: somewhere in the Western Interconnection. The paper and README don't name the site. [VERIFY] It may be Salt Lake City, where KIT recorded US_UT01, but that is a guess.
- Span (I checked every row): 2024-01-16 23:38:35 to 2024-11-18 13:25:34 UTC.
  - 26,488,020 rows, one per second, with no missing rows.
  - Rows flagged "good" (QI=0): 6,379 hours, about 87 %.
  - 258 days are at least 90 % good. The longest unbroken stretch of good days is 99 days, starting 2024-01-23.
  - Weak months: July and August 2024 (about 390 good hours each).
- Format: CSV with semicolons and columns `Time;f60;QI`.
  - Time is in UTC.
  - f60 is the deviation from 60 Hz, in mHz.
  - QI=2 rows are linear interpolation, not measurements. Mask them.
- Size: 1.11 GB uncompressed, 242 MB compressed inside the zip.
- License: CC BY 4.0. Cite the Zenodo record (De Din, Carta and Hartmann, 2025) and the paper (Hartmann et al., 2025).
- Access: free, no login. I fetched only the Western CSV, using HTTP range requests.
- Still updating: no. It is a fixed research archive.
- My checks:
  - First 20 hours: mean −3.4 mHz, standard deviation 12.6 mHz, 1-second step standard deviation 2.1 mHz.
  - Whole file: mean 59.99983 Hz, standard deviation 18.1 mHz.
  - The plot shows real grid behaviour, including the 1-minute oscillation the paper describes. Plot: $PROVENANCE_DATA/wecc_samples/zenodo_wi_2024head.png
  - The plot also shows a long straight line where a gap was filled by interpolation. Mask QI=2 rows before use.
- ENF reference use: very good for 2024 recordings. It is real, GPS-timed, in UTC, and 1-second. Nothing else public comes close.
- Ready copy: $PROVENANCE_DATA/wecc_samples/zenodo_wecc_2024_1s.npz (53 MB).
  - `t0_utc` is 2024-01-16 23:38:35 UTC as epoch seconds.
  - `f_hz` is a float32 array, one value per second, with NaN wherever QI was not 0.
  - The raw compressed copy is $PROVENANCE_DATA/wecc_samples/wi_member.bin.
- The same zip also has US Eastern data (about 2.5 weeks, 67 MB CSV), plus Australia, Iceland, South Korea, Malaysia, Mallorca, and South Africa.

### 2. John Pigott (jp3141), Phoenix AZ, 2022, 5-second log
- Data (OSF): https://osf.io/cq285, "Western Interconnection Frequency Data".
  - File: 60Hz.log.gz, 127 MB, at https://osf.io/download/pvjsb/
  - Public, no login, no license stated.
- Code and smaller logs (GitHub): https://github.com/jp3141/60Hz (MIT license).
  - Files: 60Hz.log.gz (9.9 MB, Feb 14–28, 2022, 236k rows) and "60 Hz Feb-Mar 2022.log.zip" (14 MB).
- Span: starts 2022-02-14 08:18:51. From the file size, it covers about a year. [VERIFY the end date]
- Resolution: 5 seconds. Each reading is the exact cycle count over that 5 s, against a Teensy clock disciplined to GPS 1PPS.
- Format: text CSV with columns Ticks, Cycles, Frequency, FBUS, Total Cyc, Flt, Phase, 1Hz.
- Timestamps come from the Pi's own clock, via `datetime.now()`. They are likely local Arizona time (MST, UTC−7, no daylight saving). [VERIFY] Expect about ±10–100 ms of NTP error.
- My checks on the first 8.6 days:
  - 148k rows with a median spacing of 5 s.
  - One gap, from Feb 14 08:19 to Feb 15 12:56.
  - Standard deviation 16.6 mHz; 5-second step standard deviation 4.4 mHz.
  - The author says it matches the FNET WECC display.
- Still updating: no.
- ENF reference use: good for 2022 clips, but only at 5-second resolution, and the timezone needs confirming.

### 3. nate-griff/enf: FNET gauge images turned into numbers, 2026
- Link: https://github.com/nate-griff/enf, files under `source_data/grid_data/YYYY-MM-DD.csv`.
- Method: every 38.6 s, the collector saved FNET's public gauge chart and extracted the curve from the image. That gives about 1-second points for the regions EI, WECC, ERCOT and Quebec.
- Span: 2026-03-20 to 2026-05-12 UTC. 54 daily files, about 1.06 GB in total.
- Format: CSV with columns timestamp_utc, region, frequency_hz. No license.
- Access: free raw download. Still updating: no. Nothing new after May 12, 2026 [VERIFY].
- My check on the WECC data for 2026-04-20:
  - 83,957 points with a median spacing of 0.99 s.
  - 2,479 blank values, and gaps adding up to about 0.65 h.
  - Standard deviation 22 mHz.
  - Values are clipped at 59.95 and 60.05 Hz, the edges of the gauge.
  - The regions don't correlate with each other (|r| < 0.06), which is what independent real grids should look like.
  - Plot: $PROVENANCE_DATA/wecc_samples/wecc_nategriff_20260420.png
- ENF reference use: usable, but rough. It is quantised to image pixels, clipped, and has a possible scale error [VERIFY against a known event]. Its main value is the method: anyone can run this scraper going forward.

### 4. OSF "Power grid frequency database" (KIT, Jumar et al.): US_UT01 Salt Lake City
- Link: https://osf.io/by5hu (paper: arXiv 2006.01771).
- Data: 2019-05-19 to 2019-05-25, 1 second, GPS-timed, CSV, in UTC.
- Same database: US_TX (College Station, ERCOT), about 1 week to 1 month [VERIFY].
- License: cite the authors (CC BY according to my earlier notes [VERIFY]). Free, no login. Not updating.
- Already built into the Provenance tool.
- Kaggle copy: kaggle.com/datasets/harpree/grid-frequency-data. It holds only one hour (11:00–12:00) per city, and Kaggle needs a login to download. Skip it.

### 5. LBNL Open µPMU: Berkeley CA, 2015
- Link: https://powerdata-download.lbl.gov/data/ (README cites Stewart, E.M., 2016).
- Data: 120 samples per second, phase angle and magnitude per phase. Timestamps are nanosecond epoch values in UTC.
- Span: 2015-10-01 to 2015-12-31.
- Size: each stream .gz is about 0.7–0.85 GB, roughly 130 GB in total. Free over HTTP, no login.
- My check: I downloaded the first 2 MB of `_LBNL_a6_bus1_L1ANG.gz`, which is 39 minutes from 2015-10-01 00:00 UTC.
  - Frequency taken from the rate of change of phase angle: mean 60.0009 Hz, standard deviation 10.4 mHz, 1-second step standard deviation 0.8 mHz.
  - It looks clean and realistic. Plot: $PROVENANCE_DATA/wecc_samples/lbnl_upmu_20151001.png
- Separately, powerdata-explore.lbl.gov offers an API. Access rules are unclear [VERIFY]. The archive.upmu.org plotter publishes a shared login; I did not use it.
- ENF reference use: excellent quality, but only covers late 2015, and the files are huge.

### 6. Short or coarse hobbyist records
- **Jeremy Elson (lectrobox), Seattle, June 2023**
  - Link: https://www.lectrobox.com/projects/zero-crossing-detector/
  - 3 days of every-zero-crossing timestamps (16.1 M), with a Jupyter notebook.
  - Clock: GPS-disciplined (GPSDO); UTC from NTP, good to about 100 ms.
  - Free.
- **Andy Backus, Bellingham WA, June 2019** (time-nuts list)
  - Link: https://febo.com/pipermail/time-nuts_lists.febo.com/2019-July/096847.html
  - Attachment: 2019-06.dat, 509 KB zip, which I downloaded.
  - I checked it: it holds per-minute time-error data (43,201 rows covering 30 days), not 1-second data. Too coarse for ENF.
- **Tom Van Baak, leapsecond.com, Bellevue WA, about 2013**
  - Link: http://leapsecond.com/pages/mains/
  - Every-zero-crossing logs covering about 6 hours. Times are elapsed seconds, not UTC.
  - The site returned a 500 error today [VERIFY].
- **Rob Ruark** (robruark.com/projects/grid_frequency/)
  - Live meters for the Western, Eastern and Texas grids over MQTT, GPS-timed.
  - The old graph pages are broken, and I found no public archive [VERIFY].

### 7. Listed only (login, NDA, or not continuous)
- **IEEE SP Cup 2016 ENF dataset**
  - IEEE DataPort, DOI 10.21227/H2159S.
  - Grid "II" is the Western US: short power and audio clips.
  - Needs a login.
- **FNET/GridEye (UTK)**
  - Public pages show live gauges only. Historical data has been hidden since May 2018.
  - Access is on request through the Power IT Lab. Not contacted, per your instruction.
- **PNNL National PMU Dataset**
  - Two years of data across all three US interconnections. Needs an NDA.
- **PNNL/ORNL Grid Event Signature Library (GESL)**
  - Open-access short event snippets. Provider 10 is the Western Interconnection.
  - Not continuous. Download terms [VERIFY].
- **CAISO / RC West PMU data**
  - Request-only, for RC West members, and only 60 days after an event.
- **WECC SPDP "System Frequency" page**
  - 1-minute averages and quarterly summaries only.
- **BPA, OpenEI, NREL, ASU, WSU, Caltech**
  - No public continuous frequency archive found.
- **Hugging Face, Figshare, Dryad**
  - Nothing relevant for the US. Hugging Face only has GB-grid frequency sets.
- **Reddit (r/ElectricalEngineering, Oct 2025)**
  - Someone asked for exactly this (CAISO-area frequency) and found nothing, which confirms the gap.

## Logger projects worth copying (for the Raspberry Pi 5)

1. **jp3141/60Hz (John Pigott)** — https://github.com/jp3141/60Hz (MIT). **Best overall to copy.**
   - Proven over a year of continuous logging in the WECC.
   - Hardware:
     - a 9 VAC transformer that powers everything
     - a 2-stage RC filter with a 3.3 V zener clamp feeding the Teensy's comparator
     - a Teensy that counts whole cycles against its 48 MHz clock, kept on time by GPS 1PPS
     - a Pi that logs every 5 s
   - Software: the .ino firmware, a Python logger, a systemd unit, and a gnuplot script.
   - Change for ENF: report every 1 s (the code already has an `Interval` setting; `2.0` is there, commented out) and timestamp in UTC.
2. **Jeremy Elson zero-crossing board + STM32 timestamper** — https://www.lectrobox.com/projects/zero-crossing-detector/
   - The cleanest analog front end: MCP6561 comparator, AP7375 regulator, 12 VAC wall wart.
   - Schematic published, and the board is sold.
   - Use it if you want every-cycle timestamps rather than 1-second averages.
3. **detourner/GridFreqMonitor** — https://github.com/detourner/GridFreqMonitor
   - Pi + optocoupler + GT-U7 GPS PPS, using pigpio, MQTT and systemd. Gives 1-second output.
   - Set up for 50 Hz, so the constants need changing to 60 Hz.
   - Note: pigpio does not support the Pi 5. Swap to lgpio or gpiod, or put the timing in a Pico. [VERIFY]
4. **jbolhuis/pico-grid-freq** — https://github.com/jbolhuis/pico-grid-freq
   - Pico PIO counting against a DS3232 32 kHz reference, over 120 cycles.
   - A good Pi 5 add-on, because the Pico does the timing work instead of the Pi.
5. **elfchief/powerfreq-hardware** — KiCad board for a picPET-based mains timestamper (2016). Reference only.
6. **nate-griff FNET gauge scraper**
   - No hardware needed: it records FNET's public gauge from now on.
   - Rough (clipped, pixel-limited), but free, and covers EI, WECC, ERCOT and Quebec.

**Suggested Pi 5 build:**
- Use Pigott's Teensy design, or an RP2040 Pico doing the same job, fed by a safe low-voltage AC transformer.
- Add a GPS module with PPS, wired to both the counter and the Pi so the Pi runs chrony with PPS. That puts timestamps within 1 µs of UTC.
- Log 1-second readings in UTC to CSV, with a daily rotation.
- Optionally, run the nate-griff scraper alongside it as a cross-check.

## Files from this research (local, not in this repo)
- $PROVENANCE_DATA/wecc_samples/zenodo_wecc_2024_1s.npz (ready-to-use 1-second WECC data for 2024)
- $PROVENANCE_DATA/wecc_samples/zenodo_wi_2024head.png
- $PROVENANCE_DATA/wecc_samples/lbnl_upmu_20151001.png
- $PROVENANCE_DATA/wecc_samples/wecc_nategriff_20260420.png
- $PROVENANCE_DATA/wecc_samples/jp_60Hz.log.gz (Pigott, Feb 14–28, 2022), pigott_part.gz
- $PROVENANCE_DATA/wecc_samples/backus.bin (Backus, June 2019, per-minute)

## Open [VERIFY] items
- Site of the Zenodo 2024 Western recording.
- Timezone and end date of the Pigott OSF log.
- Whether nate-griff's data has really stopped, and its scale accuracy.
- Access rules for LBNL powerdata-explore.
- Whether leapsecond.com is back up.
- Whether Rob Ruark keeps an archive.
- Download terms for GESL.
- Pi 5 GPIO library swap for GridFreqMonitor.
