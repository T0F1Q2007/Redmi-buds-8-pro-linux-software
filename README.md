# Redmi Buds 8 Pro Manager for GNOME

A native GNOME Shell extension and companion D-Bus background daemon engineered to provide complete device management, active noise cancellation (ANC) depth configuration, spatial audio rendering, and telemetry for Xiaomi Redmi Buds 8 Pro hardware on Linux systems.

---

## System Architecture

Standard Linux desktop Bluetooth subsystems (BlueZ and PipeWire) manage A2DP/HFP audio stream negotiation. However, hardware-specific parameters—such as adaptive noise suppression, multi-tier transparency, equalizer presets, and spatial head tracking—are controlled via Xiaomi's proprietary **Vela OS M-BAP** protocol.

This software suite provides a complete reverse-engineered control stack:

```
┌─────────────────────────────────────────────────────────────────┐
│                    GNOME Shell Top Panel UI                     │
│               (extension.js & custom SVG icons)                 │
└────────────────────────────────┬────────────────────────────────┘
                                 │ D-Bus IPC (org.redmibuds8.Control)
┌────────────────────────────────┴────────────────────────────────┐
│                   Background Python Service                     │
│                           (daemon.py)                           │
└────────────────────────────────┬────────────────────────────────┘
                                 │ RFCOMM / SPP (Channel 28)
┌────────────────────────────────┴────────────────────────────────┐
│                    Redmi Buds 8 Pro Hardware                    │
└─────────────────────────────────────────────────────────────────┘
```

1. **RFCOMM/SPP Control Daemon (`daemon.py`):** Maintains persistent bidirectional socket communication over Serial Port Profile (Channel 28), parses incoming M-BAP frame packets, maintains live battery levels via a 15-second background query loop, and emits JSON state payloads over D-Bus (`org.redmibuds8.Control`).
2. **Native GNOME Shell Extension (`extension.js`):** Redesigned UI adhering to Figma design specifications featuring horizontal pill buttons, custom SVG icons for distinct earbud and case telemetry, hover tooltips, light/dark theme adaptation, and custom keyboard shortcuts (`Super + -`).
3. **Audio Stabilization Module (`52-lhdc-fix.conf`):** Configures WirePlumber parameters to enforce Constant Quality (`cq`) mode and increases A2DP buffer headroom to eliminate audio underrun pops on LHDC v5 streams.

---

## UI & Design Features

* **Compact Pill Button Layout:** Segmented horizontal controls for Noise Control, Immersive Commute, and Spatial Audio replacing verbose text dropdowns.
* **Custom Symbolic SVG Icons:** Dedicated vector assets for Left Earbud, Right Earbud, Charging Case, Noise Cancellation, Transparency sub-modes (Regular, Enhanced Voice, Enhanced Ambience), Commute presets (Train, Bus, Airplane), and Spatial Audio (Dolby, Xiaomi Immersive).
* **Hover Tooltips:** Native cursor tooltips revealing full option titles when hovering over icon buttons.
* **Adaptive Light/Dark Theme Styling:** High-contrast pill buttons with dark icon inversion on active selection, seamlessly matching both GNOME Light and Dark shell themes.
* **Smart ANC & Manual Depth Slider:** Toggling Smart ANC enables adaptive noise suppression (`04 00 0B 01 00`). Disabling Smart ANC reveals a 3-tier depth slider (Deep, Balanced, Light).
* **Conditional Visibility:** Sub-options (ANC Depth, Transparency Modes, Head Tracking) automatically expand only when their parent mode is active.
* **Keyboard Navigation & Shortcut:** Press **`Super` + `-`** (`Win + -`) to toggle the extension menu directly.

---

## Technical Protocol Specifications (Vela OS M-BAP)

Communication takes place over **Bluetooth Classic RFCOMM (Channel 28)** using the Serial Port Profile UUID (`00001101-0000-1000-8000-00805f9b34fb`).

### Binary Frame Layout

All commands (Host → Earbuds) and notifications (Earbuds → Host) strictly adhere to the following sequence:

| Offset | Byte Count | Field Name | Description / Valid Values |
|---|---|---|---|
| `0x00` | 3 | Magic Header | `FE DC BA` |
| `0x03` | 1 | Message Type | `C4` (Host Command), `C7` (Notification), `04` (ACK) |
| `0x04` | 2 | Service Group | `08 00` (Hardware/ANC), `F2 00` (Settings/Audio), `0E 00` (Status) |
| `0x06` | 1 | Length | `Payload Length + 1` (Includes Sequence Byte) |
| `0x07` | 1 | Sequence ID | Monotonically incrementing counter (`0x00`–`0xFF`) |
| `0x08` | Variable | Payload | Command-specific byte parameters |
| End | 1 | Footer | `EF` |

> **Packet Parser Note:** Packet parsing walks the byte stream by inspecting `FE DC BA` headers and checking length parameters. This prevents false-positive payload matches on packet header length/sequence bytes.

---

### Mapped Payload Registry

#### Active Noise Control (ANC)
* **Main Modes (`Service Group 08 00`):**
  * Off: `02 04 00`
  * Active Noise Cancellation: `02 04 01`
  * Transparency: `02 04 02`
* **ANC Depth Levels (`Service Group F2 00`):**
  * Smart ANC (Adaptive): `04 00 0B 01 00`
  * Deep ANC: `04 00 0B 01 01`
  * Balanced ANC: `04 00 0B 01 02`
  * Light ANC: `04 00 0B 01 03`
* **Transparency Sub-modes (`Service Group F2 00`):**
  * Regular Transparency: `04 00 0B 02 02`
  * Enhanced Voice: `04 00 0B 02 00`
  * Enhanced Ambience Sound: `04 00 0B 02 01`

#### Environmental Audio & Spatial Modes
* **Immersive Commute (`Service Group F2 00`):** `03 00 67 [Mode]`
  * `00` Off | `01` Train | `02` Public Transit | `03` Airplane Engine
* **Spatial Audio Mode (`Service Group F2 00`):**
  * Off (Standard Stereo): `03 00 1D 03`
  * Dolby Audio (Static Spatial): `03 00 1D 0A`
  * Xiaomi Immersive Audio (Dimensional): `03 00 1D 0B`
* **Head Tracking (`Service Group F2 00`):**
  * Off: `03 00 68 00` | On: `03 00 68 01` (*Requires Xiaomi Immersive Audio*)

#### Battery Telemetry Decoding
Battery status is reported via notification payload tag `04 07`:
* Structure: `04 07 [LeftByte] [RightByte] [CaseByte]`
* Bits `0..6` (`val & 0x7F`): Battery level percentage (`0`–`100`).
* Bit `7` (`val & 0x80`): Charging state indicator (`1` = Charging in case).
* Value `0xFF`: Component disconnected / unavailable.

---

## Bluetooth LE Audio Compatibility Note

The **Redmi Buds 8 Pro (Chinese Edition)** does **NOT** hardware-support Bluetooth LE Audio (BAP / LC3 codec streaming):
* **UUID Analysis:** The hardware advertises Volume Control (`0x1844`), Volume Offset (`0x1845`), and Coordinated Set (`0x1846`), but lacks Published Audio Capabilities (`PACS` `0x1850`) and Audio Stream Control (`ASCS` `0x184E`).
* **Conclusion:** LE Audio profile switches will not appear in GNOME Sound Settings as the hardware lacks LE Audio BAP endpoints.

---

## Installation and Deployment

### System Prerequisites
* Linux distribution running GNOME Shell 45, 46, 47, 48, 49, or 50
* PipeWire & BlueZ audio stack
* Python 3.10+ with `dasbus` and `dbus-python` libraries

### 1. Clone & Link Extension
```bash
git clone https://github.com/T0F1Q2007/Redmi-buds-8-pro-linux-software.git
cd Redmi-buds-8-pro-linux-software

# Symlink extension to GNOME extensions directory
mkdir -p ~/.local/share/gnome-shell/extensions
ln -sf "$(pwd)" ~/.local/share/gnome-shell/extensions/buds8pro@toowfeeq
```

### 2. Configure Systemd User Service
```bash
mkdir -p ~/.config/systemd/user

cat << 'EOF' > ~/.config/systemd/user/redmibuds8.service
[Unit]
Description=Redmi Buds 8 Pro Control Daemon
After=graphical-session.target bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/.local/share/gnome-shell/extensions/buds8pro@toowfeeq/daemon.py
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now redmibuds8.service
```

### 3. Enable Extension & Compile Schemas
```bash
glib-compile-schemas schemas/
gnome-extensions enable buds8pro@toowfeeq
```
Use **`Super` + `-`** (`Win + -`) to toggle the extension menu directly from your keyboard.

---

## LHDC Audio Stabilization

High-bitrate codecs (LHDC v5) under PipeWire can experience buffer underrun pops when dynamic bitrate scaling (`lhdc-abr`) responds to minor RF fluctuations.

WirePlumber configuration (`~/.config/wireplumber/wireplumber.conf.d/52-lhdc-fix.conf`) enforces Constant Quality (`cq`) mode and increases headroom:
```hocon
monitor.bluez.properties = {
  bluez5.a2dp.lhdc-quality = "cq"
}

monitor.bluez.rules = [
  {
    matches = [ { node.name = "~bluez_output.*" } ]
    actions = {
      update-props = {
        api.alsa.headroom = 8192
        node.latency = "2048/48000"
        session.suspend-timeout-seconds = 0
      }
    }
  }
]
```

---

## Repository Structure & Branching Model

This project follows a structured Git development workflow with feature branches:
* **`main`:** Stable primary release branch.
* **`feature/ui-figma-redesign`:** Figma-compliant pill button UI, custom SVG icons, hover tooltips, and light theme styling.
* **`feature/daemon-packet-parser`:** Packet-structure parser, false-positive fix for in-ear detection, and 15s battery query timer.
* **`feature/audio-buffer-tuning`:** LHDC v5 A2DP headroom stabilization and WirePlumber buffer parameters.
* **`feature/initial-reverse-engineering`:** Protocol framing and RFCOMM channel 28 base socket communication.

---

## License

Distributed under the MIT License. Developed independently for hardware interoperability. Redmi is a registered trademark of Xiaomi Inc.
