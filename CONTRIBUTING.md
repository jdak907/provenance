# Contributing

Thanks for helping. Provenance is a privacy tool, so changes should keep it honest about what it can and can't tell.

## Set up

```bash
make install      # or: python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
make test
```

Tests must pass with no network and none of the large datasets. If a new test needs real data, make it skip cleanly when the data is missing (`pytest.mark.skipif` on the path under `PROVENANCE_DATA`).

## Ground rules

- **Numbers come from runs.** If you change a threshold, a decision rule or a scoring step, re-run the matching validation script (see the README's Testing section), update `docs/*validation*.md`, and update any number the README quotes. Mark anything you could not confirm with `[VERIFY]`.
- **Report failures too.** Abstentions and wrong answers belong in the validation docs.
- **Respect data licenses.** Do not commit third-party data. Add new sources to `DATA_SOURCES.md` with their license, attribution and how to fetch them. Do not add sources that need scraping against their terms, logins you don't own, or paid feeds.
- **Local only.** The GUI binds to 127.0.0.1. Don't add uploading of user audio anywhere.
- **Plain language** in user-facing text (GUI, Help tab, reports). Short sentences; spell out units.

## Style

- Python 3.10+, numpy/scipy/matplotlib only in the core. Optional dependencies go in an extra in `pyproject.toml`.
- One-line docstrings that say what a function returns. Keep constants named at the top of a module.
- No absolute paths. Use `PROVENANCE_DATA` (datasets) and `~/.cache/provenance` (caches).

## Pull requests

1. One topic per pull request.
2. Add or update tests.
3. Add a line to `CHANGELOG.md` under "Unreleased".
4. CI (`.github/workflows/ci.yml`) must be green.

## Responsible use

Contributions that make it easier to locate or track other people without consent will not be accepted. The tool exists to let people check their own recordings.
