#!/bin/bash
# LHDC Audio Buffer & Quality Fix for PipeWire / WirePlumber
# Solves sudden loud crackling/tweaking on high-bitrate LHDC audio

WP_CONF_DIR="$HOME/.config/wireplumber/wireplumber.conf.d"
mkdir -p "$WP_CONF_DIR"

cat << 'EOF' > "$WP_CONF_DIR/52-lhdc-fix.conf"
monitor.bluez.properties = {
  bluez5.a2dp.lhdc-quality = "cq"
  bluez5.default.rate = 48000
}
EOF

echo "Applying WirePlumber LHDC audio fix..."
systemctl --user restart wireplumber pipewire

echo "LHDC audio configuration updated successfully!"
