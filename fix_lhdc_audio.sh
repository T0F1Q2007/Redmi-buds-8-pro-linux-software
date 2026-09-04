#!/bin/bash
# LHDC Audio Buffer & Quality Stabilization Fix for PipeWire / WirePlumber
# Solves dynamic bitrate hunting, restores Headset with Mic,
# and allows true low-latency scaling during LE Mode.

WP_CONF_DIR="$HOME/.config/wireplumber/wireplumber.conf.d"
mkdir -p "$WP_CONF_DIR"

cat << 'EOF' > "$WP_CONF_DIR/52-lhdc-fix.conf"
monitor.bluez.properties = {
  # Force Constant Quality mode for LHDC to prevent dynamic ABR bitrate swings
  bluez5.a2dp.lhdc-quality = "cq"

  # Enable both High Fidelity Playback (A2DP) and Headset with Mic (HFP/HSP)
  bluez5.roles = [ a2dp_sink a2dp_source hsp_hs hsp_ag hfp_hf hfp_ag ]

  # Prevent automatic headset profile switching so music stays in high fidelity A2DP
  bluez5.autoswitch-to-headset-profile = false
}

# Prevent Bluetooth node from sleeping to eliminate initial wake-up audio clipping,
# while allowing PipeWire to scale latency dynamically between Quality and Latency profiles.
monitor.bluez.rules = [
  {
    matches = [ { node.name = "~bluez_output.*" } ]
    actions = {
      update-props = {
        session.suspend-timeout-seconds = 0
      }
    }
  }
]
EOF

echo "Applying WirePlumber audio configuration..."
systemctl --user restart wireplumber pipewire

echo "Audio configuration updated successfully!"
