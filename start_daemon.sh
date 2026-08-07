#!/bin/bash
# Start the Redmi Buds 8 Pro D-Bus Daemon

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

exec python3 "$SCRIPT_DIR/daemon.py"
