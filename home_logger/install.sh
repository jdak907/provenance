#!/usr/bin/env bash
# Set up a Raspberry Pi 5 (Raspberry Pi OS Bookworm or newer) as a 1 s UTC grid-frequency logger.
#   sudo ./install.sh            # do it
#   sudo ./install.sh --dry-run  # only print what would change
# What it does:
#   1. installs gpsd, chrony, pps-tools, python3-serial
#   2. enables the GPIO UART (GPS NMEA on GPIO14/15 -> /dev/ttyAMA0) and the PPS input on GPIO18 (-> /dev/pps0)
#   3. points gpsd at the GPS and chrony at GPS time + PPS (prefers PPS once locked)
#   4. installs grid_logger.py to /opt/gridfreq and the systemd service gridfreq-logger@<user>
#   5. adds log rotation for the logger's status log
# It never touches mains wiring, and it does not open any network ports. A reboot is needed after step 2.
set -euo pipefail
DRY=0; [[ "${1:-}" == "--dry-run" ]] && DRY=1
USER_NAME="${SUDO_USER:-${USER}}"
SRC="$(cd "$(dirname "$0")" && pwd)"
CFG=/boot/firmware/config.txt; [[ -f $CFG ]] || CFG=/boot/config.txt
run() { echo "+ $*"; [[ $DRY == 1 ]] || eval "$@"; }
add_line() {  # add_line FILE LINE  (only if missing)
  grep -qxF "$2" "$1" 2>/dev/null && echo "  ok: $2 already in $1" || run "echo '$2' >> '$1'"
}
[[ $DRY == 1 || $EUID == 0 ]] || { echo "run with sudo"; exit 1; }

echo "== 1. packages"
run "apt-get update -qq"
run "DEBIAN_FRONTEND=noninteractive apt-get install -y gpsd gpsd-clients chrony pps-tools python3-serial"

echo "== 2. UART + PPS overlay in $CFG"
add_line "$CFG" "enable_uart=1"
add_line "$CFG" "dtparam=uart0=on"
add_line "$CFG" "dtoverlay=pps-gpio,gpiopin=18"
# serial login console off, serial hardware on
if command -v raspi-config >/dev/null; then run "raspi-config nonint do_serial_cons 1"; run "raspi-config nonint do_serial_hw 0"; fi

echo "== 3. gpsd + chrony"
run "cat > /etc/default/gpsd <<'G'
DEVICES=\"/dev/ttyAMA0 /dev/pps0\"
GPSD_OPTIONS=\"-n\"
USBAUTO=\"false\"
G"
run "mkdir -p /etc/chrony/conf.d"
run "cat > /etc/chrony/conf.d/gps-pps.conf <<'C'
# GPS sentences give the second number (coarse, ~100 ms); the PPS edge gives the exact start of the second.
refclock SHM 0 refid NMEA offset 0.200 delay 0.2 noselect
refclock PPS /dev/pps0 lock NMEA refid PPS prefer poll 4
# keep internet servers as a sanity check and for when the GPS has no sky view
makestep 1 3
C"
add_line /etc/chrony/chrony.conf "confdir /etc/chrony/conf.d"
run "systemctl enable gpsd chrony"

echo "== 4. logger"
run "install -d /opt/gridfreq /var/log/gridfreq"
run "install -m 0755 '$SRC/grid_logger.py' '$SRC/convert_csv.py' '$SRC/selftest.py' '$SRC/import_to_provenance.py' '$SRC/sync_to_box.sh' /opt/gridfreq/"
run "install -m 0644 '$SRC/gridfreq-logger@.service' /etc/systemd/system/"
run "chown '$USER_NAME' /var/log/gridfreq"
run "usermod -aG dialout '$USER_NAME'"
run "install -d -o '$USER_NAME' '/home/$USER_NAME/gridfreq'"
run "systemctl daemon-reload"
run "systemctl enable 'gridfreq-logger@$USER_NAME'"

echo "== 5. log rotation"
run "install -m 0644 '$SRC/gridfreq.logrotate' /etc/logrotate.d/gridfreq"

echo
echo "Done. Next:"
echo "  1. Flash the Pico with MicroPython and copy pico/main.py to it (see home_logger_guide.md)."
echo "  2. sudo reboot   (activates the UART and PPS overlay)"
echo "  3. after the GPS has a fix (5-15 min near a window): chronyc sources   -> PPS line marked with '*'"
echo "  4. tail -f /home/$USER_NAME/gridfreq/gridfreq_\$(date -u +%F).csv"
