#!/usr/bin/env bash
# OPTIONAL: copy finished daily logs off the Pi.
# This script never uploads anywhere on its own: it syncs only to a destination you set.
# Sync to the machine that runs Provenance (rsync over SSH), then run import_to_provenance.py --from-dir there:
#        DEST=you@laptop.local:gridfreq/ ./sync_to_box.sh
# Add it to cron for a nightly copy:  15 0 * * * DEST=you@laptop.local:gridfreq/ /opt/gridfreq/sync_to_box.sh
set -euo pipefail
SRC="${SRC:-$HOME/gridfreq/}"
: "${DEST:?set DEST=user@host:path/ (nothing is sent unless you set it)}"
rsync -av --include='gridfreq_*.csv*' --exclude='*' "$SRC" "$DEST"
