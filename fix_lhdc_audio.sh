#!/bin/bash
# LHDC Audio Buffer & Quality Stabilization Fix for PipeWire / WirePlumber
# Solves dynamic bitrate hunting and keeps both Casual Headphones (A2DP/LHDC)
# and Headset with Microphone (HFP/mSBC) available.

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

# Increase internal buffer size for Bluetooth A2DP streams to reduce
# underrun-triggered audio spikes during codec processing peaks.
monitor.bluez.rules = [
  {
    matches = [ { node.name = "~bluez_output.*" } ]
    actions = {
      update-props = {
        api.alsa.headroom       = 8192
        node.latency            = "2048/48000"
        session.suspend-timeout-seconds = 0
      }
    }
  }
]
EOF

echo "Applying WirePlumber audio configuration..."
systemctl --user restart wireplumber pipewire

echo "Audio configuration updated successfully!"
