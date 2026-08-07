#!/bin/bash
# Script to start the Redmi Buds 8 Pro DBus Daemon

# Activate the virtual environment if necessary (depends on user setup)
# source /path/to/venv/bin/activate

# Make sure dbus is accessible
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

# Run the python daemon
python3 daemon.py
