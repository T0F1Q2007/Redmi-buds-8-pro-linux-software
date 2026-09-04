#!/bin/bash
# Dual-Mode Bluetooth Audio Configuration for PipeWire / WirePlumber
# Supports both Classic High Fidelity (LHDC v5 / AAC) and LE Audio (BAP with LC3)
# alongside Headset with Microphone (HFP/mSBC).

WP_CONF_DIR="$HOME/.config/wireplumber/wireplumber.conf.d"
mkdir -p "$WP_CONF_DIR"

cat << 'EOF' > "$WP_CONF_DIR/52-lhdc-fix.conf"
monitor.bluez.properties = {
  # Force Constant Quality mode for LHDC to prevent dynamic ABR bitrate swings
  bluez5.a2dp.lhdc-quality = "cq"

  # Enable High Fidelity Media (A2DP), LE Audio (BAP with LC3), and Headset (HFP)
  bluez5.roles = [ a2dp_sink a2dp_source bap_sink bap_source hsp_hs hsp_ag hfp_hf hfp_ag ]
  bluez5.enable-lc3 = true

  # Prevent automatic headset profile switching so music stays in high fidelity
  bluez5.autoswitch-to-headset-profile = false
}

# Prevent Bluetooth node from sleeping to eliminate initial wake-up audio clipping
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
