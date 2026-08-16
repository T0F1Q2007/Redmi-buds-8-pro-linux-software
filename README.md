# Redmi Buds 8 Pro Manager for GNOME

A native GNOME Shell extension and companion D-Bus background daemon engineered to provide complete device management, active noise cancellation (ANC) depth configuration, spatial audio rendering, and telemetry for Xiaomi Redmi Buds 8 Pro hardware on Linux systems.

---

## System Architecture

Standard Linux desktop Bluetooth subsystems (BlueZ and PipeWire) manage A2DP/HFP audio stream negotiation. However, hardware-specific parameters—such as adaptive noise suppression, multi-tier transparency, equalizer presets, and spatial head tracking—are controlled via Xiaomi's proprietary **Vela OS M-BAP** protocol.

This software suite provides a complete reverse-engineered control stack:

```
┌─────────────────────────────────────────────────────────────────┐
│                    GNOME Shell Top Panel UI                     │
│                        (extension.js)                           │
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

1. **RFCOMM/SPP Control Daemon (`daemon.py`):** Maintains persistent bidirectional socket communication over Serial Port Profile (Channel 28), handles packet serialization/deserialization, parses battery notifications, and exposes a D-Bus IPC interface (`org.redmibuds8.Control`).
2. **Native GNOME Shell Extension (`extension.js`):** Integrates seamlessly into the GNOME desktop environment, supplying real-time battery readouts, selective noise control sub-menus, spatial mutual-exclusion logic, and custom keyboard shortcuts.
3. **Audio Stabilization Module (`fix_lhdc_audio.sh`):** Configures WirePlumber parameters to eliminate dynamic bitrate underrun artifacts on LHDC v5 audio streams while enabling LE Audio (BAP / LC3) profiles.

---

## Technical Protocol Specifications (Vela OS M-BAP)

Communication takes place over **Bluetooth Classic RFCOMM (Channel 28)** using the Serial Port Profile UUID (`00001101-0000-1000-8000-00805f9b34fb`).

### Binary Frame Layout

All commands (Host → Earbuds) and notifications (Earbuds → Host) strictly adhere to the following sequence:

| Offset | Byte Count | Field Name | Description / Valid Values |
|---|---|---|---|
| `0x00` | 3 | Magic Header | `FE DC BA` |
| `0x03` | 1 | Message Type | `C4` (Host Command), `C7` (Notification), `04` (ACK) |
| `0x04` | 2 | Service Group | `08 00` (Hardware/ANC), `F2 00` (Settings/Audio), `09 00` (DeviceInfo) |
| `0x06` | 1 | Length | `Payload Length + 1` (Includes Sequence Byte) |
| `0x07` | 1 | Sequence ID | Monotonically incrementing counter (`0x00`–`0xFF`) |
| `0x08` | Variable | Payload | Command specific byte parameters |
| End | 1 | Footer | `EF` |

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
  * Enhanced Voice: `04 00 0B 02 00`
  * Enhanced Ambience Sound: `04 00 0B 02 01`
  * Regular Transparency: `04 00 0B 02 02`

#### Equalizer & Environmental Audio
* **Equalizer Presets (`Service Group F2 00`):** `04 00 36 01 [Preset]`
  * `01` Standard | `02` Music | `03` Video | `04` Game | `05` Audio Books
* **Immersive Commute (`Service Group F2 00`):** `03 00 67 [Mode]`
  * `00` Off | `01` Train | `02` Public Transit | `03` Airplane Engine

#### Spatial Audio & Head Tracking
* **Audio Mode (`Service Group F2 00`):**
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

### 3. Enable Extension & Shortcut
```bash
gnome-extensions enable buds8pro@toowfeeq
```
Use **`Super` + `-`** (`Win + -`) to toggle the extension menu directly from your keyboard.

---

## LHDC Audio Stabilization

High-bitrate codecs (LHDC v5) under PipeWire can experience buffer underrun pops when dynamic bitrate scaling (`lhdc-abr`) responds to minor RF fluctuations.

Execute the included optimization script to enforce Constant Quality (`cq`) mode and enable LE Audio (LC3) profile roles:
```bash
./fix_lhdc_audio.sh
```

---

## Repository Structure & Branching Model

This project follows an established Git Flow development model:
* **`master`:** Production-ready release builds.
* **`feature/daemon-state-battery`:** Daemon IPC and telemetry parsing.
* **`feature/ui-improvements-controls`:** GNOME UI components, checkmark indicators, and debouncing logic.
* **`feature/keybindings`:** GSettings schema and keyboard shortcut integration.
* **`feature/lhdc-audio-tweak-fix`:** Audio stack optimization and buffer stabilization scripts.

---

## License

Distributed under the MIT License. Developed independently for hardware interoperability. Redmi is a registered trademark of Xiaomi Inc.
