# Redmi Buds 8 Pro Manager for GNOME

A native GNOME Shell extension and companion D-Bus background daemon engineered to provide complete device management, active noise cancellation (ANC) depth configuration, spatial audio rendering, low-latency DSP gaming mode, and live telemetry for Xiaomi Redmi Buds 8 Pro hardware on Linux systems.

---

## System Architecture

Linux desktop Bluetooth subsystems (BlueZ and PipeWire) manage standard A2DP/HFP audio stream negotiation. Proprietary hardware parameters—such as adaptive noise suppression, multi-tier transparency, equalizer presets, spatial head tracking, and low-latency modes—are governed by Xiaomi's **Vela OS M-BAP** protocol.

This project implements a decoupled, three-tier architecture:

```
┌─────────────────────────────────────────────────────────────────┐
│                    GNOME Shell Top Panel UI                     │
│               (extension.js & custom SVG icons)                 │
└────────────────────────────────┬────────────────────────────────┘
                                 │ D-Bus IPC (org.redmibuds8.Control)
┌────────────────────────────────┴────────────────────────────────┐
│                   Background Python Service                     │
│               (daemon.py – Async I/O & BlueZ)                   │
└────────────────────────────────┬────────────────────────────────┘
                                 │ In-Memory Packet Handshake
┌────────────────────────────────┴────────────────────────────────┐
│              Zero-I/O Binary Protocol Engine                    │
│             (protocol.py – Framing & Parser)                    │
└────────────────────────────────┬────────────────────────────────┘
                                 │ RFCOMM / SPP (Channel 28)
┌────────────────────────────────┴────────────────────────────────┐
│                    Redmi Buds 8 Pro Hardware                    │
│                     (MAC: B8:53:84:F3:D7:D0)                    │
└─────────────────────────────────────────────────────────────────┘
```

1. **Zero-I/O Protocol Engine (`protocol.py`):** Pure functional engine handling Vela OS M-BAP packet framing, command encoding, stream fragmentation reassembly, noise recovery, and typed telemetry event parsing without OS, socket, or D-Bus dependencies. Verified by an automated unit test suite (`test_protocol.py`).
2. **Background Control Daemon (`daemon.py`):** Event-driven service running via systemd user session. Monitors BlueZ connection states, maintains persistent RFCOMM communication on Channel 28 (`Xiaomi Inc.` SPP UUID `00001101-0000-1000-8000-00805f9b34fb`), queries device status periodically, and exposes the `org.redmibuds8.Control` D-Bus IPC interface.
3. **GNOME Shell Extension (`extension.js`):** Built on a declarative `FEATURES` schema registry with control adapter bindings. Provides live battery badges, horizontal pill buttons, dynamic sliders, tooltips, responsive theme switching, and full 2D keyboard navigation.
4. **Audio Optimization Script (`fix_lhdc_audio.sh`):** Configures WirePlumber (`52-lhdc-fix.conf`) for dual-mode A2DP/BAP audio roles, enforces Constant Quality (`cq`) for LHDC v5 streams, and prevents sleep-induced audio dropouts.

---

## Key Features

* **Real-Time Battery Telemetry:** Discrete status badges for Left Earbud, Right Earbud, and Charging Case with dynamic charging indicators.
* **Segmented Noise Control:** Single-click switching between **Off**, **Active Noise Cancellation**, and **Transparency** modes.
* **Adaptive & Manual ANC Depth:** Toggle Smart Adaptive ANC or adjust depth manually across 3 tiers (Deep, Balanced, Light) via an interactive slider.
* **Transparency Profiles:** Quick selection between **Regular**, **Enhanced Voice**, and **Enhanced Ambience** sound modes.
* **Immersive Commute Presets:** Embedded environmental DSP noise filtering for **Train**, **Public Transit**, and **Airplane** noise profiles.
* **Spatial Audio & Head Tracking:** Choose between Stereo, **Dolby Audio**, and **Xiaomi Immersive Audio** with dynamic head tracking calibration.
* **Device Settings Toggles:**
  * **Gaming Mode (Low Latency DSP):** Activates low-latency gaming profiles with accompanying acoustic feedback chimes.
  * **Dual Connection (Multipoint):** Seamlessly switch between host devices.
  * **In-Ear Detection:** Automatically pause and resume playback on earbud insertion/removal.
* **Precision Vector Glyphs:** 14 custom symbolic SVG icons designed on a 16×16 grid, loaded directly via `Gio.FileIcon` to ensure consistency across any GNOME Shell theme.
* **Dual Design Themes:**
  * **Obsidian Chrome (Dark Mode):** Deep Onyx (`#0A0A0A`), Blue Slate (`#536878`), and Alabaster Grey (`#E5E4E2`).
  * **Scarlet Glacier (Light Mode):** Crisp Snow (`#FAFBFD`), Periwinkle (`#BFB4DC`), and Inferno (`#AA0003`).
* **Full Keyboard Accessibility:** Integrated 2D spatial grid navigation engine with keyboard shortcut support.

---

## Technical Protocol Specification (Vela OS M-BAP)

All communication with the earbuds transpires over Bluetooth Classic RFCOMM on **Channel 28** using the Serial Port Profile (SPP).

### Binary Frame Structure

Frames sent to or received from the hardware adhere strictly to the following byte layout:

| Byte Offset | Length | Field Name | Description |
|---|---|---|---|
| `0x00`–`0x02` | 3 bytes | Magic Header | `FE DC BA` |
| `0x03` | 1 byte | Message Type | `C4` (Host Command), `C7` (Notification), `04` (ACK) |
| `0x04`–`0x05` | 2 bytes | Service Group | `08 00` (Hardware/ANC), `F2 00` (Audio/Settings), `02 00` (Query) |
| `0x06` | 1 byte | Packet Length | Payload Length + 1 (includes Sequence ID byte) |
| `0x07` | 1 byte | Sequence ID | Monotonically incrementing counter (`0x00`–`0xFF`) |
| `0x08`–End-1 | Variable | Payload | Command arguments or telemetry payload bytes |
| End | 1 byte | Footer | `EF` |

> [!IMPORTANT]
> Naïve byte matching on raw stream buffers causes false-positive command matches (such as detecting `02 06` in header length/sequence bytes). The stream parser walks validated `FE DC BA` framing headers and extracts verified payloads exclusively from `C7` notification packets.

---

### Command & Payload Registry

#### Active Noise Control (ANC)
* **Main Modes (`Service Group 08 00` / `0E 00`):**
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
  * Enhanced Ambience: `04 00 0B 02 01`

#### Environmental & Spatial Audio
* **Immersive Commute (`Service Group F2 00`):** `03 00 67 [Mode]`
  * `00` Off | `01` Train | `02` Public Transit | `03` Airplane Engine
* **Spatial Audio Modes (`Service Group F2 00`):**
  * Off (Standard Stereo): `03 00 1D 03`
  * Dolby Audio (Static Spatial): `03 00 1D 0A`
  * Xiaomi Immersive Audio (Dynamic): `03 00 1D 0B`
* **Head Tracking (`Service Group F2 00`):**
  * Off: `03 00 68 01`
  * On: `03 00 68 00` followed by `03 00 68 02` (*requires Xiaomi Immersive mode*)

#### Device Settings & Hardware
* **Gaming Mode / Low Latency DSP (`Service Group F2 00`):**
  * Enable: `03 00 28 00` and `03 00 07 00`
  * Disable: `03 00 28 01` and `03 00 07 01`
* **Dual Connection / Multipoint (`Service Group F2 00`):**
  * Enable: `03 00 04 01` | Disable: `03 00 04 00`
* **In-Ear Detection (`Service Groups 08 00` & `F2 00`):**
  * Enable: `02 06 01` (Hardware), `03 00 24 01`, `04 00 24 01`
  * Disable: `02 06 00` (Hardware), `03 00 24 00`, `04 00 24 00`

#### Battery Telemetry Decoding
Battery status is published under notification tag `04 07`:
* Structure: `04 07 [Left] [Right] [Case]`
* Bits `0..6` (`val & 0x7F`): Percentage (`0`–`100`).
* Bit `7` (`val & 0x80`): Charging state flag (`1` = Charging, `0` = Discharging).
* Disconnected indicator: `0xFF` (`-1`).

---

## Dual-Mode Bluetooth Architecture Note

> [!NOTE]
> The hardware features a dual-mode radio controller:
> * **Classic Bluetooth (BR/EDR):** Handles high-bitrate media streaming (LHDC v5 / AAC / SBC), Headset profile (HFP/mSBC), and proprietary Vela OS device control over RFCOMM Channel 28.
> * **Bluetooth LE:** Advertises Coordinated Set Identification (`CSIS` `0x1846`), Published Audio Capabilities (`PACS` `0x1850`), and Audio Stream Control (`ASCS` `0x184E`) on a separate rotating private LE address. Linux desktops interact seamlessly with the primary Classic Bluetooth pairing for stable low-latency DSP operations.

---

## Installation & Setup

### Prerequisites
* Linux distribution with GNOME Shell 45, 46, 47, 48, 49, or 50
* BlueZ 5.65+ and PipeWire / WirePlumber audio stack
* Python 3.10+ with `dasbus` and `dbus-python` libraries

Install system dependencies (Debian/Ubuntu/Fedora/Arch):
```bash
# Ubuntu / Debian
sudo apt install python3-dasbus python3-dbus pulseaudio-utils

# Fedora
sudo dnf install python3-dasbus python3-dbus pulseaudio-utils

# Arch Linux
sudo pacman -S python-dasbus python-dbus libcanberra
```

### 1. Clone & Link Extension
```bash
git clone https://github.com/T0F1Q2007/Redmi-buds-8-pro-linux-software.git
cd Redmi-buds-8-pro-linux-software

mkdir -p ~/.local/share/gnome-shell/extensions
ln -sf "$(pwd)" ~/.local/share/gnome-shell/extensions/buds8pro@toowfeeq
```

### 2. Configure Background Daemon
Deploy the systemd user unit to manage the RFCOMM connection automatically:
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

### 3. Compile Schemas & Enable Extension
```bash
glib-compile-schemas schemas/
gnome-extensions enable buds8pro@toowfeeq
```

---

## High-Fidelity Audio Stabilization (LHDC v5)

To prevent audio underrun pops and dynamic bitrate drops on LHDC v5 connections, execute the bundled WirePlumber configuration script:

```bash
chmod +x fix_lhdc_audio.sh
./fix_lhdc_audio.sh
```

This applies `~/.config/wireplumber/wireplumber.conf.d/52-lhdc-fix.conf`:
* Enforces Constant Quality mode (`bluez5.a2dp.lhdc-quality = "cq"`).
* Configures BlueZ endpoint roles (`a2dp_sink`, `bap_sink`, `hfp_hf`).
* Disables automatic fallback to low-fidelity headset profiles (`bluez5.autoswitch-to-headset-profile = false`).
* Disables Bluetooth node auto-suspension (`session.suspend-timeout-seconds = 0`) to eliminate wake-up clipping.

---

## Keyboard Navigation & Shortcuts

The menu interface incorporates a 2D spatial grid navigation matrix:

| Keybinding | Action |
|---|---|
| `Super` + `-` (`Win` + `-`) | Toggle the extension popup menu |
| `Left` / `Right` Arrow | Navigate between horizontal pill items or adjust sliders |
| `Up` / `Down` Arrow | Navigate across control rows (Pills → Switches → Sliders) |
| `Tab` / `Shift` + `Tab` | Linear forward / backward focus traversal |
| `Enter` / `Space` | Activate selected pill button or toggle switch |
| `Escape` | Close the popup menu |

---

## Verification & Automated Testing

The protocol framing, serialization, and stream parsers are verified via a zero-dependency Python unit test suite:

```bash
python3 -m unittest discover -v
```

All 12 unit tests execute in under 5ms, covering:
* Command framing and sequence numbering
* Stream fragmentation and packet reassembly
* Noise stream recovery and garbage byte rejection
* Multi-frame burst packet handling
* Battery payload decoding and status parsing
