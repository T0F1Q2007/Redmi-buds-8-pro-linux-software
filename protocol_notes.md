# Redmi Buds 8 Pro Protocol Analysis

## Overview
The Redmi Buds 8 Pro (MAC: `B8:53:84:F3:D7:D0`) can be actively controlled via a proprietary "Vela OS" M-BAP protocol. The earbuds accept commands over **Bluetooth Classic (RFCOMM / Serial Port Profile)** on **Channel 28** ("Xiaomi Inc.").

## Packet Structure
Every command sent to and received from the earbuds follows a strict byte sequence:

1. **Header (3 bytes):** `FE DC BA` (Magic word)
2. **Message Type (1 byte):** 
   - `C4`: Command (Sent from Host to Earbuds)
   - `C7`: Notification/Response (Sent from Earbuds to Host)
   - `04`: Acknowledgment (ACK)
3. **Service / Group ID (2 bytes):**
   - `08 00`: Hardware / ANC controls
   - `F2 00`: Settings (EQ, Immersive commute, Head tracking, Audio modes)
   - `F3 00`: Other settings
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

**Acknowledgment:** `fedcba040800020013ef`
- `FE DC BA` : Header
- `04` : ACK type
- `08 00` : Hardware group
- `02` : Length (1 byte payload + 1 byte seq)
- `00` : Sequence number of the ACK packet itself
- `13` : Payload (Acknowledges the sequence number `0x13`)
- `EF` : Footer

---

## Decoded Payloads

Below are the mapped payloads discovered by reverse-engineering the HCI Bluetooth snoop logs. To form a full command, wrap these payloads in the structure outlined above using the corresponding Service Group.

### ANC & Transparency Modes
**Service Group:** `08 00`
- **ANC Off:** `02 04 00`
- **ANC On:** `02 04 01`
- **Transparency Mode:** `02 04 02`

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

### Audio Modes
**Service Group:** `F2 00`
- **Dolby Audio:** `03 00 1D 0A`
- **Xiaomi Dimensional Audio:** `03 00 1D 0B`

### Head Tracking
**Service Group:** `F2 00`
- **Off:** `03 00 68 00`
- **On:** `03 00 68 01`

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

## Battery Data
Battery information is actively broadcasted periodically over the same Channel 28 connection by the earbuds via a `C7` notification type, but the earbuds also broadcast the battery levels via BLE (Google Fast Pair UUID `0000fe2c-0000-1000-8000-00805f9b34fb`). We can extract it from the RFCOMM payload:
Look for packets starting with `fedcba` containing the payload sequence mapping to left, right, and case percentages. For example, `64 64 FF` indicates 100% Left, 100% Right, and Case Unknown (or disconnected).

## How to Communicate (Python Example)
```python
import socket

# Connect to the earbuds on RFCOMM Channel 28
s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
s.connect(("B8:53:84:F3:D7:D0", 28))

# Send the 'ANC ON' command
cmd = bytes.fromhex("fedcbac408000413020401ef")
s.send(cmd)

# Receive ACK
response = s.recv(1024)
s.close()
```
