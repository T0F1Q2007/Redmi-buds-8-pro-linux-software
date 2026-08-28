import socket
import logging
import signal
import time
import json
import dbus
import dbus.service
import dbus.mainloop.glib
from threading import Thread, Lock

from dasbus.connection import SessionMessageBus
from dasbus.server.interface import dbus_interface, dbus_signal
from dasbus.typing import Int, Bool, Str
from dasbus.loop import EventLoop
from gi.repository import GLib

MAC_ADDRESS     = "B8:53:84:F3:D7:D0"
RFCOMM_PORT     = 28
XIAOMI_UUID     = "00001101-0000-1000-8000-00805f9b34fb"  # SPP
PROFILE_PATH    = "/org/redmibuds8/profile"
DBUS_SERVICE    = "org.redmibuds8.Control"
DBUS_PATH       = "/org/redmibuds8/Control"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("redmibuds8")


class BudsConnection:
    def __init__(self, state_callback=None):
        self.sock           = None
        self.seq            = 0
        self.connected      = False
        self.lock           = Lock()
        self.state_callback = state_callback

        # State storage
        self.battery_left   = -1
        self.battery_right  = -1
        self.battery_case   = -1
        self.charging_left  = False
        self.charging_right = False
        self.charging_case  = False

        self.anc_mode       = 0  # 0: Off, 1: ANC, 2: Transparency
        self.anc_depth      = 0  # 0: Smart, 1: Deep, 2: Balanced, 3: Light
        self.trans_submode  = 2  # 0: Enhanced Voice, 1: Enhanced Ambience, 2: Regular

        self.eq_mode        = 1  # 1: Standard, 2: Music, 3: Video, 4: Game, 5: Books
        self.commute_mode   = 0  # 0: Off, 1: Train, 2: Transit, 3: Airplane

        self.in_ear_det     = True
        self.audio_mode     = 0  # 0: Off, 1: Dolby, 2: Xiaomi Immersive
        self.head_tracking  = False
        self.le_mode        = False

        self._status_timer  = None

    def get_state_dict(self):
        """Return full state as a dictionary for the StateChanged signal."""
        return {
            'connected': self.connected,
            'battery_left': self.battery_left,
            'battery_right': self.battery_right,
            'battery_case': self.battery_case,
            'charging_left': self.charging_left,
            'charging_right': self.charging_right,
            'charging_case': self.charging_case,
            'anc_mode': self.anc_mode,
            'anc_depth': self.anc_depth,
            'trans_submode': self.trans_submode,
            'eq_mode': self.eq_mode,
            'commute_mode': self.commute_mode,
            'in_ear_det': self.in_ear_det,
            'audio_mode': self.audio_mode,
            'head_tracking': self.head_tracking,
            'le_mode': self.le_mode,
        }

    def notify_state_change(self):
        if self.state_callback:
            GLib.idle_add(self.state_callback)

    def connect(self):
        """Active outbound RFCOMM connect loop with retry."""
        while True:
            try:
                log.info(f"Trying RFCOMM connect to {MAC_ADDRESS}:{RFCOMM_PORT}...")
                s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                s.settimeout(10)
                s.connect((MAC_ADDRESS, RFCOMM_PORT))
                s.settimeout(None)
                with self.lock:
                    self.sock      = s
                    self.connected = True
                log.info("Connected to earbuds RFCOMM successfully.")
                self.notify_state_change()
                self._start_periodic_query()
                self.listen_loop()
            except Exception as e:
                with self.lock:
                    self.connected = False
                    if self.sock:
                        try:
                            self.sock.close()
                        except Exception:
                            pass
                    self.sock = None
                self._stop_periodic_query()
                self.notify_state_change()
                log.warning(f"Connection failed: {e}. Retrying in 10 seconds...")
                time.sleep(10)

    def _start_periodic_query(self):
        """Periodic status query every 30 seconds to keep battery and state fresh without overwhelming RFCOMM."""
        def _do_query():
            if self.connected:
                self.query_status()
                return GLib.SOURCE_CONTINUE
            return GLib.SOURCE_REMOVE
        self._status_timer = GLib.timeout_add_seconds(30, _do_query)

    def _stop_periodic_query(self):
        if self._status_timer:
            GLib.source_remove(self._status_timer)
            self._status_timer = None

    def accept_connection(self, fd: int):
        """Accept an inbound connection handed off by BlueZ profile."""
        try:
            s = socket.fromfd(fd, socket.AF_BLUETOOTH, socket.SOCK_STREAM)
            with self.lock:
                self.sock      = s
                self.connected = True
            log.info(f"Inbound RFCOMM connection accepted (fd={fd}).")
            self.notify_state_change()
            self._start_periodic_query()
            self.listen_loop()
        except Exception as e:
            log.warning(f"accept_connection failed: {e}")
        finally:
            with self.lock:
                self.connected = False
            self._stop_periodic_query()
            self.notify_state_change()

    def listen_loop(self):
        # Query initial status upon connection
        GLib.idle_add(self.query_status)

        while self.connected:
            try:
                data = self.sock.recv(1024)
                if not data:
                    break
                self._parse_incoming(data)
            except Exception as e:
                log.warning(f"Error reading socket: {e}")
                break
        with self.lock:
            self.connected = False
        self._stop_periodic_query()
        log.info("Disconnected from earbuds.")
        self.notify_state_change()

    def query_status(self):
        """Query status from earbuds to get live battery levels and settings."""
        if self.connected:
            log.info("Querying device status...")
            self.send_cmd("0200", "ffffffff")

    def _parse_incoming(self, data: bytes):
        """Parse packets using proper RFCOMM frame structure.

        Each packet:  FE DC BA [type:1] [svc_h:1] [svc_l:1] [len:1] [seq:1] [payload:len-1] EF
        Only C7 (notification) packets are parsed for state; 04 (ACK) packets are ignored
        to prevent false-positive hex matches.
        """
        state_changed = False

        # Data may contain multiple concatenated packets
        i = 0
        while i < len(data) - 3:
            # Look for packet header FE DC BA
            if data[i] != 0xFE or data[i+1] != 0xDC or data[i+2] != 0xBA:
                i += 1
                continue

            # Need at least header(3) + type(1) + svc(2) + len(1) + seq(1) + footer(1) = 9 bytes
            if i + 8 > len(data):
                break

            pkt_type = data[i + 3]
            svc_h    = data[i + 4]
            svc_l    = data[i + 5]
            length   = data[i + 6]   # payload_len + 1 (for seq byte)
            # seq    = data[i + 7]

            payload_len = length - 1
            if payload_len < 0:
                i += 1
                continue

            pkt_end = i + 8 + payload_len  # position of EF footer
            if pkt_end >= len(data):
                # Incomplete packet, try raw battery fallback then stop
                break

            payload = data[i + 8 : i + 8 + payload_len]
            svc = (svc_h << 8) | svc_l

            log.info(f"Packet: type=0x{pkt_type:02X} svc=0x{svc:04X} len={length} payload={payload.hex()}")

            # Only process notification/response (C7) packets
            if pkt_type == 0xC7:
                state_changed |= self._handle_notification(svc, payload)

            i = pkt_end + 1  # skip past EF footer

        # Fallback: scan for Battery Tag 04 07 [L] [R] [C] in the entire hex stream
        # This handles compound status dumps where battery data may appear outside
        # the standard packet structure.
        hex_data = data.hex()
        tag_pos = hex_data.find("0407")
        if tag_pos != -1 and len(hex_data) >= tag_pos + 10:
            state_changed |= self._parse_battery(hex_data, tag_pos)

        if state_changed:
            self.notify_state_change()

    def _handle_notification(self, svc, payload):
        """Handle a properly parsed notification payload. Returns True if state changed."""
        changed = False

        if svc == 0x0800 or svc == 0x0E00:
            # Hardware service group – ANC mode & In-Ear Detection
            if len(payload) >= 3 and payload[0] == 0x02 and payload[1] == 0x04:
                mode = payload[2]
                if mode in (0, 1, 2) and mode != self.anc_mode:
                    self.anc_mode = mode
                    log.info(f"ANC mode from device: {mode}")
                    changed = True
            if len(payload) >= 3 and payload[0] == 0x02 and payload[1] == 0x06:
                val = bool(payload[2])
                if val != self.in_ear_det:
                    self.in_ear_det = val
                    log.info(f"In-ear detection from device: {val}")
                    changed = True

        elif svc == 0xF200:
            # Settings service group
            if len(payload) >= 4:
                # ANC Depth: 04 00 0B 01 [depth]
                if payload[:4] == bytes([0x04, 0x00, 0x0B, 0x01]) and len(payload) >= 5:
                    depth = payload[4]
                    if depth in (0, 1, 2, 3) and depth != self.anc_depth:
                        self.anc_depth = depth
                        log.info(f"ANC depth from device: {depth}")
                        changed = True
                # Transparency Sub-mode: 04 00 0B 02 [sub]
                elif payload[:4] == bytes([0x04, 0x00, 0x0B, 0x02]) and len(payload) >= 5:
                    sub = payload[4]
                    if sub in (0, 1, 2) and sub != self.trans_submode:
                        self.trans_submode = sub
                        log.info(f"Transparency sub-mode from device: {sub}")
                        changed = True
                # Audio mode: 03 00 1D [mode]
                elif payload[:3] == bytes([0x03, 0x00, 0x1D]) and len(payload) >= 4:
                    raw = payload[3]
                    mode_map = {0x03: 0, 0x0A: 1, 0x0B: 2}
                    mode = mode_map.get(raw)
                    if mode is not None and mode != self.audio_mode:
                        self.audio_mode = mode
                        log.info(f"Audio mode from device: {mode}")
                        changed = True
                # Head tracking: 03 00 68 [val] (0x01=OFF, 0x00/0x02=ON)
                elif payload[:3] == bytes([0x03, 0x00, 0x68]) and len(payload) >= 4:
                    val = (payload[3] != 0x01)
                    if val != self.head_tracking:
                        self.head_tracking = val
                        log.info(f"Head tracking from device: {val}")
                        changed = True
                # Commute mode: 03 00 67 [val]
                elif payload[:3] == bytes([0x03, 0x00, 0x67]) and len(payload) >= 4:
                    val = payload[3]
                    if val in (0, 1, 2, 3) and val != self.commute_mode:
                        self.commute_mode = val
                        log.info(f"Commute mode from device: {val}")
                        changed = True
                # LE Mode / Low Latency: 03 00 28 [val] (0x00=ON, 0x01=OFF)
                elif (payload[:3] == bytes([0x03, 0x00, 0x28]) or payload[:3] == bytes([0x03, 0x00, 0x07])) and len(payload) >= 4:
                    val = (payload[3] == 0x00)
                    if val != self.le_mode:
                        self.le_mode = val
                        log.info(f"LE mode from device: {val}")
                        changed = True

        return changed

    def _parse_battery(self, hex_data, tag_pos):
        """Parse battery tag: 04 07 [L] [R] [C]."""
        try:
            raw_l = int(hex_data[tag_pos + 4:tag_pos + 6], 16)
            raw_r = int(hex_data[tag_pos + 6:tag_pos + 8], 16)
            raw_c = int(hex_data[tag_pos + 8:tag_pos + 10], 16)

            def decode_bat(val):
                if val == 0xFF:
                    return -1, False
                level = val & 0x7F
                charging = bool(val & 0x80)
                return (level if level <= 100 else -1), charging

            l_level, l_chg = decode_bat(raw_l)
            r_level, r_chg = decode_bat(raw_r)
            c_level, c_chg = decode_bat(raw_c)

            changed = (l_level != self.battery_left or r_level != self.battery_right
                       or c_level != self.battery_case)

            self.battery_left   = l_level
            self.battery_right  = r_level
            self.battery_case   = c_level
            self.charging_left  = l_chg
            self.charging_right = r_chg
            self.charging_case  = c_chg

            log.info(f"Battery: L={self.battery_left}%{'⚡' if l_chg else ''} "
                     f"R={self.battery_right}%{'⚡' if r_chg else ''} "
                     f"C={self.battery_case}%{'⚡' if c_chg else ''}")
            return changed
        except Exception as e:
            log.warning(f"Error parsing battery tag: {e}")
            return False

    def send_cmd(self, svc_hex: str, payload_hex: str):
        if not self.connected or not self.sock:
            log.warning("Cannot send command, not connected.")
            return False

        with self.lock:
            self.seq = (self.seq + 1) % 256
            seq_val = self.seq

        length    = len(payload_hex) // 2 + 1
        cmd_hex   = f"fedcbac4{svc_hex}{length:02x}{seq_val:02x}{payload_hex}ef"
        cmd_bytes = bytes.fromhex(cmd_hex)

        try:
            self.sock.send(cmd_bytes)
            log.info(f"Sent: {cmd_hex}")
            return True
        except Exception as e:
            log.warning(f"Failed to send command: {e}")
            with self.lock:
                self.connected = False
            self.notify_state_change()
            return False


class XiaomiProfile(dbus.service.Object):
    """BlueZ Profile1 implementation for inbound connections."""
    def __init__(self, bus, buds_conn: BudsConnection):
        super().__init__(bus, PROFILE_PATH)
        self._conn = buds_conn

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        log.info("Profile released.")

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, path, fd, properties):
        fd_int = int(fd)
        log.info(f"BlueZ inbound connection from {path} fd={fd_int}")
        t = Thread(target=self._conn.accept_connection, args=(fd_int,), daemon=True)
        t.start()

    @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
    def RequestDisconnection(self, path):
        log.info(f"RequestDisconnection from {path}")
        self._conn.connected = False
        if self._conn.sock:
            try:
                self._conn.sock.close()
            except Exception:
                pass


@dbus_interface(DBUS_SERVICE)
class BudsInterface:
    def __init__(self, connection: BudsConnection):
        self.conn = connection

    @dbus_signal
    def StateChanged(self, state_json: Str):
        """Signal carrying full JSON state so the extension never reads stale cached properties."""
        pass

    def _emit_state(self):
        """Build JSON state and emit StateChanged."""
        state = json.dumps(self.conn.get_state_dict())
        self.StateChanged(state)

    # Methods
    def SetAncMode(self, mode: Int):
        log.info(f"DBus call: SetAncMode({mode})")
        self.conn.anc_mode = mode
        self.conn.send_cmd("0800", f"0204{mode:02x}")
        self._emit_state()

    def SetAncDepth(self, depth: Int):
        log.info(f"DBus call: SetAncDepth({depth})")
        self.conn.anc_depth = depth
        self.conn.send_cmd("f200", f"04000b01{depth:02x}")
        self._emit_state()

    def SetTransparencySubmode(self, submode: Int):
        log.info(f"DBus call: SetTransparencySubmode({submode})")
        self.conn.trans_submode = submode
        self.conn.send_cmd("f200", f"04000b02{submode:02x}")
        self._emit_state()

    def SetEqMode(self, mode: Int):
        log.info(f"DBus call: SetEqMode({mode})")
        self.conn.eq_mode = mode
        self.conn.send_cmd("f200", f"04003601{mode:02x}")
        self._emit_state()

    def SetImmersiveCommute(self, mode: Int):
        log.info(f"DBus call: SetImmersiveCommute({mode})")
        self.conn.commute_mode = mode
        self.conn.send_cmd("f200", f"030067{mode:02x}")
        self._emit_state()

    def SetInEarDetection(self, enabled: Bool):
        log.info(f"DBus call: SetInEarDetection({enabled})")
        self.conn.in_ear_det = enabled
        if enabled:
            self.conn.send_cmd("0800", "020601")
            self.conn.send_cmd("f200", "03002401")
            self.conn.send_cmd("f200", "04002401")
        else:
            self.conn.send_cmd("0800", "020600")
            self.conn.send_cmd("f200", "03002400")
            self.conn.send_cmd("f200", "04002400")
        self._emit_state()

    def SetAudioMode(self, mode: Int):
        log.info(f"DBus call: SetAudioMode({mode})")
        self.conn.audio_mode = mode
        payload_map = {0: "03001d03", 1: "03001d0a", 2: "03001d0b"}
        p = payload_map.get(mode, "03001d0a")
        self.conn.send_cmd("f200", p)
        if mode in (0, 1) and self.conn.head_tracking:
            self.conn.head_tracking = False
            self.conn.send_cmd("f200", "03006801")
        self._emit_state()

    def SetHeadTracking(self, enabled: Bool):
        log.info(f"DBus call: SetHeadTracking({enabled})")
        self.conn.head_tracking = enabled
        if enabled:
            if self.conn.audio_mode != 2:
                self.conn.audio_mode = 2
                self.conn.send_cmd("f200", "03001d0b")
            self.conn.send_cmd("f200", "03006800")
            self.conn.send_cmd("f200", "03006802")
        else:
            self.conn.send_cmd("f200", "03006801")
        self._emit_state()

    def SetLeMode(self, enabled: Bool):
        log.info(f"DBus call: SetLeMode({enabled})")
        self.conn.le_mode = enabled
        val = 0 if enabled else 1
        self.conn.send_cmd("f200", f"030028{val:02x}")
        self.conn.send_cmd("f200", f"030007{val:02x}")
        self._emit_state()

    # Properties (kept for introspection / fallback)
    @property
    def Connected(self) -> Bool:
        return self.conn.connected

    @property
    def LeMode(self) -> Bool:
        return self.conn.le_mode

    @property
    def BatteryLeft(self) -> Int:
        return self.conn.battery_left

    @property
    def BatteryRight(self) -> Int:
        return self.conn.battery_right

    @property
    def BatteryCase(self) -> Int:
        return self.conn.battery_case

    @property
    def AncMode(self) -> Int:
        return self.conn.anc_mode

    @property
    def AncDepth(self) -> Int:
        return self.conn.anc_depth

    @property
    def TransparencySubmode(self) -> Int:
        return self.conn.trans_submode

    @property
    def EqMode(self) -> Int:
        return self.conn.eq_mode

    @property
    def ImmersiveCommute(self) -> Int:
        return self.conn.commute_mode

    @property
    def InEarDetection(self) -> Bool:
        return self.conn.in_ear_det

    @property
    def AudioMode(self) -> Int:
        return self.conn.audio_mode

    @property
    def HeadTracking(self) -> Bool:
        return self.conn.head_tracking


def register_bluez_profile(system_bus, buds_conn: BudsConnection):
    profile_obj = XiaomiProfile(system_bus, buds_conn)
    manager = dbus.Interface(
        system_bus.get_object("org.bluez", "/org/bluez"),
        "org.bluez.ProfileManager1"
    )
    opts = {
        "AutoConnect": dbus.Boolean(True),
        "Name": dbus.String("XiaomiMBAP"),
        "Channel": dbus.UInt16(RFCOMM_PORT),
    }
    manager.RegisterProfile(PROFILE_PATH, XIAOMI_UUID, opts)
    log.info(f"BlueZ profile registered: UUID={XIAOMI_UUID} channel={RFCOMM_PORT}")
    return profile_obj


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    system_bus  = dbus.SystemBus()
    session_bus = SessionMessageBus()

    buds_interface_holder = [None]

    def on_state_change():
        if buds_interface_holder[0]:
            try:
                buds_interface_holder[0]._emit_state()
            except Exception as e:
                log.warning(f"Error emitting StateChanged signal: {e}")

    buds_conn = BudsConnection(state_callback=on_state_change)

    try:
        profile_obj = register_bluez_profile(system_bus, buds_conn)
    except Exception as e:
        log.warning(f"Could not register BlueZ profile: {e}")

    conn_thread = Thread(target=buds_conn.connect, daemon=True)
    conn_thread.start()

    interface = BudsInterface(buds_conn)
    buds_interface_holder[0] = interface

    session_bus.publish_object(DBUS_PATH, interface)
    session_bus.register_service(DBUS_SERVICE)
    log.info(f"D-Bus service registered as {DBUS_SERVICE}")

    loop = EventLoop()

    def on_shutdown(*_):
        log.info("Shutting down.")
        loop.quit()

    signal.signal(signal.SIGTERM, on_shutdown)
    signal.signal(signal.SIGINT,  on_shutdown)

    loop.run()
    session_bus.disconnect()


if __name__ == "__main__":
    main()
