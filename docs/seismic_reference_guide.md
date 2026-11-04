# Seismic grid-frequency reference: how to run it on this computer

This guide covers the "US West (seismic)" reference in Provenance. It runs on this computer only. There is
no hardware to buy, wire or install. Everything comes from public seismometer data over the internet.

## What it is

Many seismometers near power lines pick up a faint 60 hertz hum from the grid. The hum follows the grid
frequency exactly, so a group of stations that agree with one another gives a second-by-second log of the
grid frequency. Provenance turns that into a reference the grid race can use, just like the Zenodo or FNET logs.

There are two commands:

- `provenance enf-rebuild` builds whole past days from the public seismic archive.
- `provenance enf-collect` follows today's live data and adds a new block every ten minutes.

Both write the same daily files, and the race picks them up on its own. In the race and the GUI the source
is labeled "US West (seismic)".

## Before you start

Use the Provenance virtual environment in the project folder, so the `provenance` command is on your path:

    cd provenance   # the repository root
    source .venv/bin/activate

You need an internet connection that can reach normal web addresses (port 443). No account, key or sign-up
is used.

## Rebuild past days

To rebuild one day for the Western grid (times are UTC days):

    provenance enf-rebuild --grid US-WEST --start 2024-04-17

To rebuild a range:

    provenance enf-rebuild --grid US-WEST --start 2024-04-01 --end 2024-04-07

To rebuild yesterday:

    provenance enf-rebuild --grid US-WEST --yesterday

If the live collector already wrote part of a day, add `--fill-only`. That keeps the live seconds and only
fills the gaps.

A day takes about two to three minutes the first time, mostly download time. The per-station hum tracks are
cached, so running the same day again takes a few seconds.

Texas and Eastern grid options exist, but they are not usable yet. In the 2024 test days the Texas stations
did not agree with one another, so no Texas consensus was written. Treat those options as experimental.

## Run the live collector

To run until you stop it with Control C:

    provenance enf-collect

To run for a fixed time, for example two hours:

    provenance enf-collect --minutes 120

To keep it running after you close the terminal:

    nohup provenance enf-collect > ~/enf-collect.log 2>&1 &

and to stop it later:

    pkill -f "provenance enf-collect"

What it does:

- It opens one secure connection to the EarthScope live data server and streams about sixteen stations.
- At start it asks for the last thirty minutes, so it can judge the stations straight away.
- Every ten minutes it checks which stations agree, takes the middle value of the trusted ones, and adds
  those six hundred seconds to today's file.
- At midnight UTC it compresses the finished day.
- It never saves raw waveforms. It keeps only a forty-minute buffer in memory.

Expect a warm-up on the very first start. A station has to pass three ten-minute checks before it counts,
so the first half hour or so writes nothing. The collector saves which stations it trusts, so if you
restart it within an hour it picks up where it left off, with no warm-up.

If the connection goes quiet for two minutes, for example after the computer sleeps, the collector
reconnects on its own and asks the server for the data it missed. The server keeps only a limited
recent buffer, so after a long break there will be a hole. Fill it from the archive afterwards with
`provenance enf-rebuild --grid US-WEST --start <day> --fill-only`. In a test on November 3, 2026 the archive
already held data up to a few minutes before the request.

## Where the files go

By default the files go in `~/.cache/provenance/enf/us/seismic/`, one folder per grid. In each folder:

- `YYYY-MM-DD.csv` is today's file while it grows. Each row is a UTC time, a frequency in hertz, the number
  of stations used, the spread between them in millihertz, and a quality word.
- `YYYY-MM-DD.csv.gz` is a finished day.
- `YYYY-MM-DD.json` is the summary for a rebuilt day: coverage and which stations were trusted.
- `status.json` is the live status: when it last updated, which stations are streaming, and which are trusted.
- `gate_state.json` holds the trust state the collector reuses after a restart.

Use `--out-dir` on either command to write somewhere else. The race only looks in the default folder.

## Check that it is working

Look at the live status:

    cat ~/.cache/provenance/enf/us/seismic/US-WEST/status.json

A healthy collector updates this file every ten minutes and lists at least three trusted stations. The log
warns when fewer than three are trusted.

Check that the race can see the data:

    python -c "from provenance_fx.enf import us_refs; print(us_refs.coverage('US-WEST'))"

The seismic entries list the days and hours it covers.

In the GUI's grid tab, the seismic log shows in the coverage chart. To try it on its own, tick
"US West: use the seismic log alone". That hides the Zenodo log for that run.

## Optional radio cross-check

Some public web radio receivers carry mains hum in their audio. The collector can listen to one now and then
and compare it with the seismic result. It is off by default. To turn it on, write a small file such as
`sdr.json`:

    {"minutes_per_hour": 10, "receivers": [{"host": "fullerton.w6mfb.com", "offset_hz": 0}]}

and run:

    provenance enf-collect --sdr-config sdr.json

It uses the receiver's normal public web page interface, listens to whatever the receiver is already tuned
to, uses one receiver at a time for ten minutes each hour, and stores no audio. Results go to
`sdr_crosscheck.jsonl` in the US-WEST folder. Radios never feed the reference. They are a check only. Ask
the receiver's operator before you run it for long stretches.

## How good it is

On eight 2024 days, checked against the Zenodo Western grid log, the seismic reference covered the whole
day and matched with a correlation of about 0.99 and a typical error of about 2 millihertz. See
`enf_validation.md`, section 14, for the full numbers and the race results.

## Limits and things to check

- EarthScope plans to require an account for archive downloads from December 15, 2026. After that,
  `provenance enf-rebuild` may stop working without one. Whether the anonymous live stream stays open is also
  unknown. [VERIFY]
- Only the Western grid is validated. Texas and Eastern are experimental.
- The live server allows only a few connections per user, so run one collector at a time.
- Raspberry Shake data is not used, because of its license.
