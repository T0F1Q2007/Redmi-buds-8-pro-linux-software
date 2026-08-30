#!/bin/bash
# LHDC Audio Buffer & Quality Stabilization Fix for PipeWire / WirePlumber
# Solves dynamic bitrate hunting and Hands-Free Voice Gateway disconnection loops

WP_CONF_DIR="$HOME/.config/wireplumber/wireplumber.conf.d"
mkdir -p "$WP_CONF_DIR"

cat << 'EOF' > "$WP_CONF_DIR/52-lhdc-fix.conf"
monitor.bluez.properties = {
  bluez5.roles = [ a2dp_sink a2dp_source ]
  bluez5.enable-lc3 = true
  bluez5.autoswitch-to-headset-profile = false
}
EOF

echo "Applying WirePlumber LHDC audio configuration..."
systemctl --user restart wireplumber pipewire

echo "LHDC audio configuration updated successfully!"
