"""
Redmi Buds 8 Pro Control Daemon
High-efficiency background service for Xiaomi Vela OS M-BAP over RFCOMM Channel 28.
Exposes org.redmibuds8.Control D-Bus IPC service.
"""

import os
import sys
import logging
import signal
import socket
import time
import json
from threading import Thread, Lock

# Dynamic origin resolution for protocol module
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import protocol as proto

import dbus
import dbus.service
import dbus.mainloop.glib
from dasbus.connection import SessionMessageBus
from dasbus.server.interface import dbus_interface, dbus_signal
from dasbus.typing import Int, Bool, Str
from dasbus.loop import EventLoop
from gi.repository import GLib

MAC_ADDRESS  = "B8:53:84:F3:D7:D0"
RFCOMM_PORT  = 28
XIAOMI_UUID  = "00001101-0000-1000-8000-00805f9b34fb"  # SPP
PROFILE_PATH = "/org/redmibuds8/profile"
DBUS_SERVICE = "org.redmibuds8.Control"
DBUS_PATH    = "/org/redmibuds8/Control"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("redmibuds8")


class BudsConnection:
    """Manages RFCOMM socket communication and Vela OS packet serialization."""

    def __init__(self, state_callback=None):
        self.sock           = None
        self.seq            = 0
        self.connected      = False
        self.lock           = Lock()
        self.state_callback = state_callback
        self._status_timer  = None
        self._recv_buffer   = b""

        # State cache
        self.battery_left   = -1
        self.battery_right  = -1
        self.battery_case   = -1
        self.charging_left  = False
        self.charging_right = False
        self.charging_case  = False

        self.anc_mode       = 0   # 0: Off, 1: ANC, 2: Transparency
        self.anc_depth      = 0   # 0: Smart, 1: Deep, 2: Balanced, 3: Light
        self.trans_submode  = 2   # 0: Voice, 1: Ambience, 2: Regular

        self.eq_mode        = 1   # 1: Standard, 2: Music, 3: Video, 4: Game, 5: Books
        self.commute_mode   = 0   # 0: Off, 1: Train, 2: Transit, 3: Airplane

        self.in_ear_det     = True
        self.audio_mode     = 0   # 0: Off, 1: Dolby, 2: Xiaomi Immersive
        self.head_tracking  = False
        self.le_mode        = False
        self.dual_connect   = True

    def get_state_dict(self):
        """Return full telemetry dictionary for D-Bus StateChanged signal."""
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
            'dual_connect': self.dual_connect,
        }

    def notify_state_change(self):
        if self.state_callback:
            GLib.idle_add(self.state_callback)

    def is_bluez_connected(self, system_bus):
        """Check if BlueZ reports an active Bluetooth connection across any hci controller."""
        try:
            manager = dbus.Interface(system_bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
            objects = manager.GetManagedObjects()
            target_mac = MAC_ADDRESS.upper()
            for path, interfaces in objects.items():
                if "org.bluez.Device1" in interfaces:
                    dev_props = interfaces["org.bluez.Device1"]
                    addr = str(dev_props.get("Address", "")).upper()
                    if addr == target_mac:
                        return bool(dev_props.get("Connected", False))
            return False
        except Exception as e:
            log.warning(f"Error querying BlueZ connection state: {e}")
            return False

    def connect_loop(self, system_bus):
        """Event-driven RFCOMM loop: connects ONLY when BlueZ is actively paired/connected."""
        while True:
            if not self.is_bluez_connected(system_bus):
                was_connected = False
                with self.lock:
                    if self.connected or self.sock is not None:
                        was_connected = True
                        self.connected = False
                        self.battery_left  = -1
                        self.battery_right = -1
                        self.battery_case  = -1
                        if self.sock:
                            try:
                                self.sock.close()
                            except Exception:
                                pass
                        self.sock = None
                if was_connected:
                    self._stop_periodic_query()
                    self.notify_state_change()
                    log.info("Earbuds disconnected in BlueZ. Sleeping RFCOMM without polling.")
                time.sleep(3)
                continue

            if not self.connected:
                try:
                    log.info(f"Earbuds active in BlueZ. Connecting RFCOMM {MAC_ADDRESS}:{RFCOMM_PORT}...")
                    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                    s.settimeout(8)
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
                    log.warning(f"RFCOMM connection attempt failed: {e}. Retrying in 5s...")
                    time.sleep(5)
            else:
                time.sleep(2)

    def _start_periodic_query(self):
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
        """Handle BlueZ Profile1 inbound connection handoff."""
        try:
            s = socket.fromfd(fd, socket.AF_BLUETOOTH, socket.SOCK_STREAM)
            try:
                os.close(fd)
            except Exception:
                pass
            with self.lock:
                self.sock      = s
                self.connected = True
            log.info(f"Inbound RFCOMM connection accepted.")
            self.notify_state_change()
            self._start_periodic_query()
            self.listen_loop()
        except Exception as e:
            log.warning(f"accept_connection failed: {e}")
        finally:
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

    def next_seq(self) -> int:
        with self.lock:
            self.seq = (self.seq + 1) % 256
            return self.seq

    def set_seq(self, seq: int):
        with self.lock:
            self.seq = seq % 256

    def send_bytes(self, cmd_bytes: bytes) -> bool:
        if not self.connected or not self.sock:
            return False
        try:
            self.sock.send(cmd_bytes)
            log.info(f"Sent command: {cmd_bytes.hex()}")
            return True
        except Exception as e:
            log.warning(f"Failed to send command: {e}")
            with self.lock:
                self.connected = False
            self.notify_state_change()
            return False

    def send_cmd(self, svc_hex: str, payload_hex: str) -> bool:
        svc = int(svc_hex, 16)
        payload = bytes.fromhex(payload_hex)
        return self.send_bytes(proto.build_frame(svc, payload, self.next_seq()))

    def query_status(self):
        if self.connected:
            self.send_bytes(proto.encode_query_status(self.next_seq()))

    def listen_loop(self):
        GLib.idle_add(self.query_status)
        self._recv_buffer = b""
        while self.connected:
            try:
                data = self.sock.recv(1024)
                if not data:
                    break
                log.info(f"Received from earbuds: {data.hex()}")
                self._parse_incoming(data)
            except Exception as e:
                log.warning(f"Error reading socket: {e}")
                break
        with self.lock:
            self.connected = False
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
        self._stop_periodic_query()
        log.info("Disconnected from earbuds.")
        self.notify_state_change()

    def _parse_incoming(self, data: bytes):
        self._recv_buffer += data
        events, self._recv_buffer = proto.parse_stream(self._recv_buffer)
        if not events:
            return

        state_changed = False
        for event in events:
            if isinstance(event, proto.AncModeEvent):
                if event.mode != self.anc_mode:
                    self.anc_mode = event.mode
                    state_changed = True
            elif isinstance(event, proto.AncDepthEvent):
                if event.depth != self.anc_depth:
                    self.anc_depth = event.depth
                    state_changed = True
            elif isinstance(event, proto.TransparencySubmodeEvent):
                if event.submode != self.trans_submode:
                    self.trans_submode = event.submode
                    state_changed = True
            elif isinstance(event, proto.AudioModeEvent):
                if event.mode != self.audio_mode:
                    self.audio_mode = event.mode
                    state_changed = True
            elif isinstance(event, proto.HeadTrackingEvent):
                if event.enabled != self.head_tracking:
                    self.head_tracking = event.enabled
                    state_changed = True
            elif isinstance(event, proto.CommuteModeEvent):
                if event.mode != self.commute_mode:
                    self.commute_mode = event.mode
                    state_changed = True
            elif isinstance(event, proto.LeModeEvent):
                if event.enabled != self.le_mode:
                    self.le_mode = event.enabled
                    state_changed = True
            elif isinstance(event, proto.DualConnectionEvent):
                if event.enabled != self.dual_connect:
                    self.dual_connect = event.enabled
                    state_changed = True
            elif isinstance(event, proto.InEarDetectionEvent):
                if event.enabled != self.in_ear_det:
                    self.in_ear_det = event.enabled
                    state_changed = True
            elif isinstance(event, proto.BatteryEvent):
                changed = (event.left != self.battery_left or event.right != self.battery_right or event.case != self.battery_case)
                self.battery_left, self.charging_left   = event.left, event.charging_left
                self.battery_right, self.charging_right = event.right, event.charging_right
                self.battery_case, self.charging_case   = event.case, event.charging_case
                state_changed |= changed

        if state_changed:
            self.notify_state_change()


class XiaomiProfile(dbus.service.Object):
    def __init__(self, bus, buds_conn: BudsConnection):
        super().__init__(bus, PROFILE_PATH)
        self._conn = buds_conn

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        log.info("Profile released.")

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, path, fd, properties):
        try:
            real_fd = fd.take() if hasattr(fd, "take") else int(fd)
            t = Thread(target=self._conn.accept_connection, args=(real_fd,), daemon=True)
            t.start()
        except Exception as e:
            log.warning(f"Error accepting NewConnection from BlueZ: {e}")

    @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
    def RequestDisconnection(self, path):
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
        pass

    def _emit_state(self):
        self.StateChanged(json.dumps(self.conn.get_state_dict()))

    def SetAncMode(self, mode: Int):
        self.conn.anc_mode = mode
        self.conn.send_bytes(proto.encode_anc_mode(mode, self.conn.next_seq()))
        self._emit_state()

    def SetAncDepth(self, depth: Int):
        self.conn.anc_depth = depth
        self.conn.send_bytes(proto.encode_anc_depth(depth, self.conn.next_seq()))
        self._emit_state()

    def SetTransparencySubmode(self, submode: Int):
        self.conn.trans_submode = submode
        self.conn.send_bytes(proto.encode_transparency_submode(submode, self.conn.next_seq()))
        self._emit_state()

    def SetEqMode(self, mode: Int):
        self.conn.eq_mode = mode
        self.conn.send_bytes(proto.encode_eq_mode(mode, self.conn.next_seq()))
        self._emit_state()

    def SetImmersiveCommute(self, mode: Int):
        self.conn.commute_mode = mode
        self.conn.send_bytes(proto.encode_commute_mode(mode, self.conn.next_seq()))
        self._emit_state()

    def SetInEarDetection(self, enabled: Bool):
        self.conn.in_ear_det = enabled
        frames, next_seq = proto.encode_in_ear_detection(enabled, self.conn.next_seq())
        for f in frames:
            self.conn.send_bytes(f)
        self.conn.set_seq(next_seq)
        self._emit_state()

    def SetAudioMode(self, mode: Int):
        self.conn.audio_mode = mode
        self.conn.send_bytes(proto.encode_audio_mode(mode, self.conn.next_seq()))
        if mode in (0, 1) and self.conn.head_tracking:
            self.conn.head_tracking = False
            frames, next_seq = proto.encode_head_tracking(False, self.conn.next_seq(), mode)
            for f in frames:
                self.conn.send_bytes(f)
            self.conn.set_seq(next_seq)
        self._emit_state()

    def SetHeadTracking(self, enabled: Bool):
        self.conn.head_tracking = enabled
        if enabled and self.conn.audio_mode != 2:
            self.conn.audio_mode = 2
        frames, next_seq = proto.encode_head_tracking(enabled, self.conn.next_seq(), self.conn.audio_mode)
        for f in frames:
            self.conn.send_bytes(f)
        self.conn.set_seq(next_seq)
        self._emit_state()

    def SetLeMode(self, enabled: Bool):
        log.info(f"DBus SetLeMode({enabled})")
        self.conn.le_mode = enabled
        frames, next_seq = proto.encode_le_mode(enabled, self.conn.next_seq())
        for f in frames:
            self.conn.send_bytes(f)
        self.conn.set_seq(next_seq)
        self._emit_state()

    def SetDualConnection(self, enabled: Bool):
        log.info(f"DBus SetDualConnection({enabled})")
        self.conn.dual_connect = enabled
        self.conn.send_bytes(proto.encode_dual_connection(enabled, self.conn.next_seq()))
        self._emit_state()

    # D-Bus Property accessors
    @property
    def Connected(self) -> Bool:
        return self.conn.connected

    @property
    def DualConnection(self) -> Bool:
        return self.conn.dual_connect

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

    @property
    def LeMode(self) -> Bool:
        return self.conn.le_mode


def register_bluez_profile(system_bus, buds_conn: BudsConnection):
    profile_obj = XiaomiProfile(system_bus, buds_conn)
    manager = dbus.Interface(
        system_bus.get_object("org.bluez", "/org/bluez"),
        "org.bluez.ProfileManager1"
    )
    opts = {
        "AutoConnect": dbus.Boolean(False),
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

    holder = [None]
    def on_state_change():
        if holder[0]:
            try:
                holder[0]._emit_state()
            except Exception as e:
                log.warning(f"Error emitting StateChanged signal: {e}")

    buds_conn = BudsConnection(state_callback=on_state_change)

    try:
        register_bluez_profile(system_bus, buds_conn)
    except Exception as e:
        log.warning(f"Could not register BlueZ profile: {e}")

    conn_thread = Thread(target=buds_conn.connect_loop, args=(system_bus,), daemon=True)
    conn_thread.start()

    interface = BudsInterface(buds_conn)
    holder[0] = interface

    session_bus.publish_object(DBUS_PATH, interface)
    session_bus.register_service(DBUS_SERVICE)
    log.info(f"D-Bus service registered as {DBUS_SERVICE}")

    loop = EventLoop()
    def on_shutdown(*_):
        log.info("Shutting down daemon.")
        loop.quit()

    signal.signal(signal.SIGTERM, on_shutdown)
    signal.signal(signal.SIGINT,  on_shutdown)
    loop.run()
    session_bus.disconnect()


if __name__ == "__main__":
    main()
