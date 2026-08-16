import socket
import logging
import signal
import time
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

        self.anc_mode       = 1  # 0: Off, 1: ANC, 2: Transparency
        self.anc_depth      = 0  # 0: Smart, 1: Deep, 2: Balanced, 3: Light
        self.trans_submode  = 2  # 0: Regular, 1: Enhanced Voice, 2: Enhanced Ambience

        self.eq_mode        = 1  # 1: Standard, 2: Music, 3: Video, 4: Game, 5: Books
        self.commute_mode   = 0  # 0: Off, 1: Train, 2: Transit, 3: Airplane

        self.in_ear_det     = True
        self.audio_mode     = 1  # 0: Off, 1: Dolby, 2: Xiaomi Immersive
        self.head_tracking  = False

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
                self.notify_state_change()
                log.warning(f"Connection failed: {e}. Retrying in 5 seconds...")
                time.sleep(5)

    def accept_connection(self, fd: int):
        """Accept an inbound connection handed off by BlueZ profile."""
        try:
            s = socket.fromfd(fd, socket.AF_BLUETOOTH, socket.SOCK_STREAM)
            with self.lock:
                self.sock      = s
                self.connected = True
            log.info(f"Inbound RFCOMM connection accepted (fd={fd}).")
            self.notify_state_change()
            self.listen_loop()
        except Exception as e:
            log.warning(f"accept_connection failed: {e}")
        finally:
            with self.lock:
                self.connected = False
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
        log.info("Disconnected from earbuds.")
        self.notify_state_change()

    def query_status(self):
        """Query status from earbuds to get live battery levels and settings."""
        if self.connected:
            log.info("Querying device status...")
            self.send_cmd("0200", "ffffffff")

    def _parse_incoming(self, data: bytes):
        """Parse battery levels and status reports from notification packets."""
        hex_data = data.hex()
        log.info(f"Rcvd hex ({len(data)} bytes): {hex_data[:120]}")

        # Look for Battery Tag 04 07 [L] [R] [C]
        tag_pos = hex_data.find("0407")
        if tag_pos != -1 and len(hex_data) >= tag_pos + 10:
            try:
                raw_l = int(hex_data[tag_pos+4:tag_pos+6], 16)
                raw_r = int(hex_data[tag_pos+6:tag_pos+8], 16)
                raw_c = int(hex_data[tag_pos+8:tag_pos+10], 16)

                def decode_bat(val):
                    if val == 0xFF:
                        return -1, False
                    level = val & 0x7F
                    charging = bool(val & 0x80)
                    return (level if level <= 100 else -1), charging

                l_level, l_chg = decode_bat(raw_l)
                r_level, r_chg = decode_bat(raw_r)
                c_level, c_chg = decode_bat(raw_c)

                self.battery_left  = l_level
                self.battery_right = r_level
                self.battery_case  = c_level

                log.info(f"Battery parsed: Left={self.battery_left}% ({'⚡' if l_chg else ''}), Right={self.battery_right}% ({'⚡' if r_chg else ''}), Case={self.battery_case}% ({'⚡' if c_chg else ''})")
                self.notify_state_change()
            except Exception as e:
                log.warning(f"Error parsing battery tag: {e}")



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
    def StateChanged(self):
        pass

    # Methods
    def SetAncMode(self, mode: Int):
        log.info(f"DBus call: SetAncMode({mode})")
        self.conn.anc_mode = mode
        self.conn.send_cmd("0800", f"0204{mode:02x}")
        self.StateChanged()

    def SetAncDepth(self, depth: Int):
        log.info(f"DBus call: SetAncDepth({depth})")
        self.conn.anc_depth = depth
        self.conn.send_cmd("f200", f"04000b01{depth:02x}")
        self.StateChanged()

    def SetTransparencySubmode(self, submode: Int):
        log.info(f"DBus call: SetTransparencySubmode({submode})")
        self.conn.trans_submode = submode
        self.conn.send_cmd("f200", f"04000b02{submode:02x}")
        self.StateChanged()

    def SetEqMode(self, mode: Int):
        log.info(f"DBus call: SetEqMode({mode})")
        self.conn.eq_mode = mode
        self.conn.send_cmd("f200", f"04003601{mode:02x}")
        self.StateChanged()

    def SetImmersiveCommute(self, mode: Int):
        log.info(f"DBus call: SetImmersiveCommute({mode})")
        self.conn.commute_mode = mode
        self.conn.send_cmd("f200", f"030067{mode:02x}")
        self.StateChanged()

    def SetInEarDetection(self, enabled: Bool):
        log.info(f"DBus call: SetInEarDetection({enabled})")
        self.conn.in_ear_det = enabled
        mode = 1 if enabled else 0
        self.conn.send_cmd("0800", f"0206{mode:02x}")
        self.StateChanged()

    def SetAudioMode(self, mode: Int):
        # 0: Off (03), 1: Dolby (0A), 2: Xiaomi Immersive (0B)
        log.info(f"DBus call: SetAudioMode({mode})")
        self.conn.audio_mode = mode
        payload_map = {0: "03001d03", 1: "03001d0a", 2: "03001d0b"}
        p = payload_map.get(mode, "03001d0a")
        self.conn.send_cmd("f200", p)
        
        # If Dolby Audio or Off is selected, Head Tracking must be turned off
        if mode in (0, 1) and self.conn.head_tracking:
            self.conn.head_tracking = False
            self.conn.send_cmd("f200", "03006800")
            
        self.StateChanged()

    def SetHeadTracking(self, enabled: Bool):
        log.info(f"DBus call: SetHeadTracking({enabled})")
        self.conn.head_tracking = enabled
        
        # Head tracking requires Xiaomi Immersive Audio (mode 2)
        if enabled and self.conn.audio_mode != 2:
            self.conn.audio_mode = 2
            self.conn.send_cmd("f200", "03001d0b")
            
        mode_val = 1 if enabled else 0
        self.conn.send_cmd("f200", f"030068{mode_val:02x}")
        self.StateChanged()

    # Properties
    @property
    def Connected(self) -> Bool:
        return self.conn.connected

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
                buds_interface_holder[0].StateChanged()
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
