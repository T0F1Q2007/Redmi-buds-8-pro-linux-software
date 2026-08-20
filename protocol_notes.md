# Redmi Buds 8 Pro Protocol Analysis

## Overview
The Redmi Buds 8 Pro (MAC: `B8:53:84:F3:D7:D0`) can be actively controlled via a proprietary "Vela OS" M-BAP protocol over **Bluetooth Classic (RFCOMM / Serial Port Profile)** on **Channel 28** ("Xiaomi Inc.").

## Packet Structure
Every command sent to and received from the earbuds follows a strict byte sequence:

1. **Header (3 bytes):** `FE DC BA` (Magic word)
2. **Message Type (1 byte):** 
   - `C4`: Command (Sent from Host to Earbuds)
   - `C7`: Notification/Response (Sent from Earbuds to Host)
   - `04`: Acknowledgment (ACK)
3. **Service / Group ID (2 bytes):**
   - `08 00`: Hardware / Core ANC & In-Ear controls
   - `F2 00`: Settings (EQ, Immersive commute, Head tracking, Audio modes, ANC depth, Sub-modes)
   - `F3 00`: Extended query & status sync
   - `09 00`: Device Info / Connection settings
4. **Length (1 byte):** `Payload Length + 1` (The +1 accounts for the Sequence Number byte)
5. **Sequence Number (1 byte):** A sequentially incrementing hex value (e.g., `10`, `11`, `12`...) used to track commands and match ACKs.
6. **Payload (Variable length):** The actual command data/bytes for the setting.
7. **Footer (1 byte):** `EF`

### Example
**Command:** `fedcbac408000413020401ef` (Turn ANC ON)
- `FE DC BA` : Header
- `C4` : Command type
- `08 00` : Hardware group
- `04` : Length (3 bytes payload + 1 byte seq)
- `13` : Sequence number (0x13)
- `02 04 01` : Payload (ANC ON)
- `EF` : Footer

---

## Decoded Payloads

### Main Noise Control Modes
**Service Group:** `08 00`
- **ANC Off:** `02 04 00`
- **ANC On:** `02 04 01`
- **Transparency Mode:** `02 04 02`

### ANC Depth & Smart ANC Sub-modes
**Service Group:** `F2 00`
- **Smart Noise Cancellation ON:** `04 00 0B 01 00`
- **Deep ANC (Manual Depth 1):** `04 00 0B 01 01`
- **Balanced ANC (Manual Depth 2):** `04 00 0B 01 02`
- **Light ANC (Manual Depth 3):** `04 00 0B 01 03`

### Transparency Sub-modes
**Service Group:** `F2 00`
- **Enhanced Voice:** `04 00 0B 02 00`
- **Enhanced Ambience Sound:** `04 00 0B 02 01`
- **Regular Transparency:** `04 00 0B 02 02`

### Immersive Commute (Background Sounds)
**Service Group:** `F2 00`
- **Off:** `03 00 67 00`
- **Train:** `03 00 67 01`
- **Public Transit:** `03 00 67 02`
- **Airplane:** `03 00 67 03`

### Scene Rendering (Equalizer / EQ)
**Service Group:** `F2 00`
- **Standard:** `04 00 36 01 01`
- **Music:** `04 00 36 01 02`
- **Video:** `04 00 36 01 03`
- **Game:** `04 00 36 01 04`
- **Audio Books:** `04 00 36 01 05`

### Audio Modes (Spatial / Dimensional Audio)
**Service Group:** `F2 00`
- **Dimensional Audio OFF:** `03 00 1D 03`
- **Dolby Audio:** `03 00 1D 0A` (Static Spatial, Head Tracking disabled)
- **Xiaomi Immersive Audio:** `03 00 1D 0B` (Supports Head Tracking)

### Head Tracking
**Service Group:** `F2 00`
- **Off:** `03 00 68 00`
- **On:** `03 00 68 01` (*Requires Xiaomi Immersive Audio `03 00 1D 0B`*)

### In-Ear Detection
**Service Group:** `08 00`
- **Off:** `02 06 00`
- **On:** `02 06 01`

### Dual Connection (Multipoint)
**Service Group:** `F2 00`
- **Off:** `03 00 04 00`
- **On:** `03 00 04 01`

### Take Calls Automatically
**Service Group:** `F2 00`
- **Off:** `03 00 03 00`
- **On:** `03 00 03 01`

### Ear Fit Test
**Service Group:** `F2 00`
- **Trigger Test:** `03 00 05 01`

---

## Battery Data Protocol
Battery levels are reported in status packets (or `C7` notifications):
- Look for tag `04 07` in status sequence: `04 07 [LeftHex] [RightHex] [CaseHex]`
- `64` = 100%, `5F` = 95%, `FF` = Unknown / Disconnected.
- Bit 7 (`val & 0x80`) = charging flag. Bits 0-6 (`val & 0x7F`) = percentage.

---

## Parsing Notes (Critical)

### False-Positive Hex String Matching
**Bug discovered 2026-08-20:** Naïve `hex_data.find("0206")` matches ANY occurrence
of `0206` in the raw hex stream, including packet **length** + **sequence number**
bytes in headers. For example, packet `FE DC BA C7 07 00 02 06 01 EF` has:
- Service group `07 00`, length `02`, seq `06`, payload `01`
- But `0206` falsely matches as In-Ear Detection payload `02 06 [val]`

**Fix:** Parse packets using proper frame structure — walk through `FE DC BA` headers,
extract type/service/length/seq/payload, and only process payloads from `C7`
(notification) packets, ignoring `04` (ACK) packets.

### Service Group 0x0E00
Observed in status responses. Functions identically to `0x0800` for ANC mode
reporting: `02 04 [mode]` payloads appear in both `0x0800` and `0x0E00` service groups.

### Service Group 0xF400
Observed in periodic notifications. Contains settings state echoes but with different
payload prefixes than `0xF200`. May be a read-only mirror of `0xF200` settings.

---

## LE Audio / BAP / LC3 Compatibility

The **Redmi Buds 8 Pro (Chinese Edition)** does NOT support Bluetooth LE Audio:
- **Missing UUIDs:** No PACS (`0x1850`), ASCS (`0x184E`), or BAP profiles advertised.
- **Present UUIDs:** Volume Control (`0x1844`), Volume Offset Control (`0x1845`),
  Coordinated Set Identification (`0x1846`) — these are GATT services but NOT
  sufficient for LE Audio streaming.
- **Conclusion:** LC3 / BAP streaming is a hardware limitation, not configurable.

