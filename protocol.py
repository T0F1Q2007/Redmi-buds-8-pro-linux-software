"""
Redmi Buds 8 Pro – Zero-I/O Binary Protocol Engine

Encapsulates packet framing, command encoding, and telemetry parsing
for the Xiaomi RFCOMM protocol without OS, socket, or D-Bus dependencies.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional, Union

# Protocol Magic Bytes and Markers
FRAME_HEADER   = b'\xfe\xdc\xba'
FRAME_TRAILER  = 0xEF
CMD_MARKER     = 0xC4
NOTIF_MARKER   = 0xC7
BATTERY_TAG    = b'\x04\x07'

# Service IDs
SVC_QUERY      = 0x0200
SVC_ANC        = 0x0800
SVC_ANC_ALT    = 0x0E00
SVC_EXT        = 0xF200


# ─── Telemetry Event Definitions ──────────────────────────────
@dataclass(frozen=True)
class AncModeEvent:
    mode: int  # 0: Off, 1: Noise Cancellation, 2: Transparency

@dataclass(frozen=True)
class AncDepthEvent:
    depth: int  # 0: Smart/Adaptive, 1: Deep, 2: Balanced, 3: Mild

@dataclass(frozen=True)
class TransparencySubmodeEvent:
    submode: int  # 0: Voice, 1: Ambience, 2: Regular

@dataclass(frozen=True)
class AudioModeEvent:
    mode: int  # 0: Off (Stereo), 1: Dolby, 2: Xiaomi Immersive

@dataclass(frozen=True)
class HeadTrackingEvent:
    enabled: bool

@dataclass(frozen=True)
class CommuteModeEvent:
    mode: int  # 0: Off, 1: Train, 2: Transit, 3: Airplane

@dataclass(frozen=True)
class LeModeEvent:
    enabled: bool

@dataclass(frozen=True)
class DualConnectionEvent:
    enabled: bool

@dataclass(frozen=True)
class InEarDetectionEvent:
    enabled: bool

@dataclass(frozen=True)
class BatteryEvent:
    left: int
    charging_left: bool
    right: int
    charging_right: bool
    case: int
    charging_case: bool

ProtocolEvent = Union[
    AncModeEvent, AncDepthEvent, TransparencySubmodeEvent, AudioModeEvent,
    HeadTrackingEvent, CommuteModeEvent, LeModeEvent, DualConnectionEvent,
    InEarDetectionEvent, BatteryEvent
]


# ─── Command Encoders ─────────────────────────────────────────
def build_frame(svc: int, payload: bytes, seq: int) -> bytes:
    """Build a complete RFCOMM command frame: FE DC BA C4 [svc:2] [len:1] [seq:1] [payload] EF."""
    length = len(payload) + 1
    header = bytes([
        0xFE, 0xDC, 0xBA, CMD_MARKER,
        (svc >> 8) & 0xFF, svc & 0xFF,
        length & 0xFF, seq & 0xFF
    ])
    return header + payload + bytes([FRAME_TRAILER])


def encode_query_status(seq: int) -> bytes:
    """Status query frame: svc 0200, payload ffffffff."""
    return build_frame(SVC_QUERY, b'\xff\xff\xff\xff', seq)


def encode_anc_mode(mode: int, seq: int) -> bytes:
    """Set ANC mode (0: Off, 1: ANC, 2: Transparency)."""
    return build_frame(SVC_ANC, bytes([0x02, 0x04, mode & 0xFF]), seq)


def encode_anc_depth(depth: int, seq: int) -> bytes:
    """Set ANC depth (0: Adaptive, 1: Deep, 2: Balanced, 3: Mild)."""
    return build_frame(SVC_EXT, bytes([0x04, 0x00, 0x0B, 0x01, depth & 0xFF]), seq)


def encode_transparency_submode(submode: int, seq: int) -> bytes:
    """Set Transparency submode (0: Voice, 1: Ambience, 2: Regular)."""
    return build_frame(SVC_EXT, bytes([0x04, 0x00, 0x0B, 0x02, submode & 0xFF]), seq)


def encode_eq_mode(mode: int, seq: int) -> bytes:
    """Set EQ mode."""
    return build_frame(SVC_EXT, bytes([0x04, 0x00, 0x36, 0x01, mode & 0xFF]), seq)


def encode_commute_mode(mode: int, seq: int) -> bytes:
    """Set Immersive Commute sound mode (0: Off, 1: Train, 2: Transit, 3: Airplane)."""
    return build_frame(SVC_EXT, bytes([0x03, 0x00, 0x67, mode & 0xFF]), seq)


def encode_in_ear_detection(enabled: bool, seq_start: int) -> Tuple[List[bytes], int]:
    """Return frames required to toggle in-ear detection and the next sequence counter."""
    val = 1 if enabled else 0
    seq = seq_start
    frames = [
        build_frame(SVC_ANC, bytes([0x02, 0x06, val]), seq),
        build_frame(SVC_EXT, bytes([0x03, 0x00, 0x24, val]), (seq + 1) % 256),
        build_frame(SVC_EXT, bytes([0x04, 0x00, 0x24, val]), (seq + 2) % 256),
    ]
    return frames, (seq + 3) % 256


def encode_audio_mode(mode: int, seq: int) -> bytes:
    """Set Spatial Audio mode (0: Stereo, 1: Dolby, 2: Xiaomi)."""
    p_map = {0: b'\x03\x00\x1d\x03', 1: b'\x03\x00\x1d\x0a', 2: b'\x03\x00\x1d\x0b'}
    payload = p_map.get(mode, b'\x03\x00\x1d\x0a')
    return build_frame(SVC_EXT, payload, seq)


def encode_head_tracking(enabled: bool, seq_start: int, current_audio_mode: int) -> Tuple[List[bytes], int]:
    """Return frames to configure head tracking and the next sequence counter."""
    frames = []
    seq = seq_start
    if enabled:
        if current_audio_mode != 2:
            frames.append(build_frame(SVC_EXT, b'\x03\x00\x1d\x0b', seq))
            seq = (seq + 1) % 256
        frames.append(build_frame(SVC_EXT, b'\x03\x00\x68\x00', seq))
        seq = (seq + 1) % 256
        frames.append(build_frame(SVC_EXT, b'\x03\x00\x68\x02', seq))
        seq = (seq + 1) % 256
    else:
        frames.append(build_frame(SVC_EXT, b'\x03\x00\x68\x01', seq))
        seq = (seq + 1) % 256
    return frames, seq


def encode_le_mode(enabled: bool, seq_start: int) -> Tuple[List[bytes], int]:
    """Return frames to toggle LE mode and the next sequence counter."""
    val = 0 if enabled else 1
    seq = seq_start
    frames = [
        build_frame(SVC_EXT, bytes([0x03, 0x00, 0x28, val]), seq),
        build_frame(SVC_EXT, bytes([0x03, 0x00, 0x07, val]), (seq + 1) % 256),
    ]
    return frames, (seq + 2) % 256


def encode_dual_connection(enabled: bool, seq: int) -> bytes:
    """Set Multipoint Dual Connection (1: enabled, 0: disabled)."""
    val = 1 if enabled else 0
    return build_frame(SVC_EXT, bytes([0x03, 0x00, 0x04, val]), seq)


# ─── Inbound Frame & Battery Parsers ──────────────────────────
def _decode_battery_byte(v: int) -> Tuple[int, bool]:
    if v == 0xFF:
        return -1, False
    level = v & 0x7F if (v & 0x7F) <= 100 else -1
    charging = bool(v & 0x80)
    return level, charging


def parse_battery_tag(data: bytes) -> Optional[BatteryEvent]:
    """Parse tag 04 07 [raw_l] [raw_r] [raw_c]."""
    idx = data.find(BATTERY_TAG)
    if idx != -1 and len(data) >= idx + 5:
        raw_l = data[idx + 2]
        raw_r = data[idx + 3]
        raw_c = data[idx + 4]
        l_level, l_chg = _decode_battery_byte(raw_l)
        r_level, r_chg = _decode_battery_byte(raw_r)
        c_level, c_chg = _decode_battery_byte(raw_c)
        return BatteryEvent(
            left=l_level, charging_left=l_chg,
            right=r_level, charging_right=r_chg,
            case=c_level, charging_case=c_chg
        )
    return None


def parse_notification(svc: int, payload: bytes) -> Optional[ProtocolEvent]:
    """Parse notification payload into a typed ProtocolEvent."""
    if svc in (SVC_ANC, SVC_ANC_ALT):
        if len(payload) >= 3 and payload[0] == 0x02:
            if payload[1] == 0x04 and payload[2] in (0, 1, 2):
                return AncModeEvent(mode=payload[2])
            elif payload[1] == 0x06:
                return InEarDetectionEvent(enabled=bool(payload[2]))

    elif svc == SVC_EXT and len(payload) >= 4:
        if payload[:4] == b'\x04\x00\x0b\x01' and len(payload) >= 5:
            if payload[4] in (0, 1, 2, 3):
                return AncDepthEvent(depth=payload[4])
        elif payload[:4] == b'\x04\x00\x0b\x02' and len(payload) >= 5:
            if payload[4] in (0, 1, 2):
                return TransparencySubmodeEvent(submode=payload[4])
        elif payload[:3] == b'\x03\x00\x1d':
            mode = {0x03: 0, 0x0A: 1, 0x0B: 2}.get(payload[3])
            if mode is not None:
                return AudioModeEvent(mode=mode)
        elif payload[:3] == b'\x03\x00\x68':
            return HeadTrackingEvent(enabled=(payload[3] != 0x01))
        elif payload[:3] == b'\x03\x00\x67':
            if payload[3] in (0, 1, 2, 3):
                return CommuteModeEvent(mode=payload[3])
        elif payload[:3] in (b'\x03\x00\x28', b'\x03\x00\x07'):
            return LeModeEvent(enabled=(payload[3] == 0x00))
        elif payload[:3] == b'\x03\x00\x04':
            return DualConnectionEvent(enabled=bool(payload[3]))

    return None


def parse_stream(buffer: bytes) -> Tuple[List[ProtocolEvent], bytes]:
    """
    Parse all complete frames and battery tags from an incoming stream buffer.
    Returns (list_of_events, remaining_unparsed_buffer).
    """
    events: List[ProtocolEvent] = []
    i = 0
    last_consumed = 0

    while i <= len(buffer) - 3:
        # Search for frame header FE DC BA
        hdr_pos = buffer.find(FRAME_HEADER, i)
        if hdr_pos == -1:
            break

        i = hdr_pos
        # Header (3) + Type (1) + SVC (2) + Len (1) + Seq (1) = 8 bytes minimum
        if i + 8 > len(buffer):
            break

        pkt_type = buffer[i + 3]
        svc      = (buffer[i + 4] << 8) | buffer[i + 5]
        length   = buffer[i + 6]
        payload_len = length - 1

        if payload_len < 0:
            i += 1
            continue

        pkt_end = i + 8 + payload_len
        if pkt_end >= len(buffer):
            break

        payload = buffer[i + 8 : pkt_end]
        if pkt_type == NOTIF_MARKER:
            event = parse_notification(svc, payload)
            if event:
                events.append(event)

        # Check for trailer EF if present
        if pkt_end < len(buffer) and buffer[pkt_end] == FRAME_TRAILER:
            i = pkt_end + 1
        else:
            i = pkt_end
        last_consumed = i

    # Check for battery telemetry in the stream
    bat_event = parse_battery_tag(buffer)
    if bat_event:
        events.append(bat_event)

    remaining = buffer[last_consumed:] if last_consumed > 0 else buffer
    return events, remaining
