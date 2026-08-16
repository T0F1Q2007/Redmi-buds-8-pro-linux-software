#!/bin/bash
# LHDC Audio Buffer & Quality Stabilization Fix for PipeWire / WirePlumber
# Solves dynamic bitrate hunting and buffer underrun crackle on high-bitrate LHDC audio

WP_CONF_DIR="$HOME/.config/wireplumber/wireplumber.conf.d"
mkdir -p "$WP_CONF_DIR"

cat << 'EOF' > "$WP_CONF_DIR/52-lhdc-fix.conf"
monitor.bluez.properties = {
  bluez5.a2dp.lhdc-quality = "cq"
  bluez5.roles = [ a2dp_sink a2dp_source bap_sink bap_source hsp_hs hsp_ag hfp_hf hfp_ag ]
  bluez5.enable-lc3 = true
}
EOF

echo "Applying WirePlumber LHDC audio configuration..."
systemctl --user restart wireplumber pipewire

echo "LHDC audio configuration updated successfully!"
