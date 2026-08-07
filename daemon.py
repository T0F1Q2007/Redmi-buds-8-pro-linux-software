import socket
import logging
import signal
import time
import dbus
import dbus.service
import dbus.mainloop.glib
from threading import Thread

from dasbus.connection import SessionMessageBus
from dasbus.server.interface import dbus_interface, dbus_signal
from dasbus.typing import Int, Bool, Str
from dasbus.loop import EventLoop
from gi.repository import GLib

MAC_ADDRESS     = "B8:53:84:F3:D7:D0"
RFCOMM_PORT     = 29
XIAOMI_UUID     = "db764ac8-4b08-7f25-aafe-59d03c27bae3"
PROFILE_PATH    = "/org/redmibuds8/profile"
DBUS_SERVICE    = "org.redmibuds8.Control"
DBUS_PATH       = "/org/redmibuds8/Control"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("redmibuds8")


class BudsConnection:
    def __init__(self):
        self.sock      = None
        self.seq       = 0
        self.connected = False

    def connect(self):
        """Active outbound RFCOMM connect loop with retry."""
        while True:
            try:
                log.info(f"Trying RFCOMM connect to {MAC_ADDRESS}:{RFCOMM_PORT}...")
                s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                s.settimeout(10)
                s.connect((MAC_ADDRESS, RFCOMM_PORT))
                s.settimeout(None)
                self.sock      = s
                self.connected = True
                log.info("Connected to earbuds RFCOMM successfully.")
                self.listen_loop()
            except Exception as e:
                self.connected = False
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass
                self.sock = None
                log.warning(f"Connection failed: {e}. Retrying in 5 seconds...")
                time.sleep(5)

    def accept_connection(self, fd: int):
        """Accept an inbound connection handed off by BlueZ profile."""
        try:
            s = socket.fromfd(fd, socket.AF_BLUETOOTH, socket.SOCK_STREAM)
            self.sock      = s
            self.connected = True
            log.info(f"Inbound RFCOMM connection accepted (fd={fd}).")
            self.listen_loop()
        except Exception as e:
            log.warning(f"accept_connection failed: {e}")
        finally:
            self.connected = False

    def listen_loop(self):
        while self.connected:
            try:
                data = self.sock.recv(1024)
                if not data:
                    break
                log.debug(f"Rcvd: {data.hex()}")
            except Exception as e:
                log.warning(f"Error reading socket: {e}")
                break
        self.connected = False
        log.info("Disconnected from earbuds.")

    def send_cmd(self, svc_hex: str, payload_hex: str):
        if not self.connected or not self.sock:
            log.warning("Cannot send command, not connected.")
            return False

        self.seq = (self.seq + 1) % 256
        length   = len(payload_hex) // 2 + 1
        cmd_hex  = f"fedcbac4{svc_hex}{length:02x}{self.seq:02x}{payload_hex}ef"
        cmd_bytes = bytes.fromhex(cmd_hex)

        try:
            self.sock.send(cmd_bytes)
            log.info(f"Sent: {cmd_hex}")
            return True
        except Exception as e:
            log.warning(f"Failed to send command: {e}")
            self.connected = False
            return False


class XiaomiProfile(dbus.service.Object):
    """BlueZ Profile1 implementation that accepts inbound connections from the earbuds."""

    def __init__(self, bus, buds_conn: BudsConnection):
        super().__init__(bus, PROFILE_PATH)
        self._conn = buds_conn

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        log.info("Profile released.")

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, path, fd, properties):
        fd_int = int(fd)
        log.info(f"BlueZ gave us an inbound connection from {path} fd={fd_int}")
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
    def StatusChanged(self):
        pass

    def SetAncMode(self, mode: Int):
        log.info(f"DBus call: SetAncMode({mode})")
        self.conn.send_cmd("0800", f"0204{mode:02x}")

    def SetEqMode(self, mode: Int):
        log.info(f"DBus call: SetEqMode({mode})")
        self.conn.send_cmd("f200", f"04003601{mode:02x}")

    def SetImmersiveCommute(self, mode: Int):
        log.info(f"DBus call: SetImmersiveCommute({mode})")
        self.conn.send_cmd("f200", f"030067{mode:02x}")

    def SetInEarDetection(self, enabled: Bool):
        log.info(f"DBus call: SetInEarDetection({enabled})")
        self.conn.send_cmd("0800", f"0206{1 if enabled else 0:02x}")

    def SetHeadTracking(self, enabled: Bool):
        log.info(f"DBus call: SetHeadTracking({enabled})")
        self.conn.send_cmd("f200", f"030068{1 if enabled else 0:02x}")

    def SetAudioMode(self, dolby: Bool):
        log.info(f"DBus call: SetAudioMode({dolby})")
        self.conn.send_cmd("f200", f"03001d{0x0a if dolby else 0x0b:02x}")

    @property
    def Connected(self) -> Bool:
        return self.conn.connected


def register_bluez_profile(system_bus, buds_conn: BudsConnection):
    """Register the Xiaomi UUID profile with BlueZ so earbuds can connect back to us."""
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

    buds_conn = BudsConnection()

    # Register BlueZ profile (inbound) — earbuds may initiate connection
    try:
        profile_obj = register_bluez_profile(system_bus, buds_conn)
    except Exception as e:
        log.warning(f"Could not register BlueZ profile: {e}")

    # Also try active outbound connection in a background thread
    conn_thread = Thread(target=buds_conn.connect, daemon=True)
    conn_thread.start()

    # Publish D-Bus control service
    interface = BudsInterface(buds_conn)
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
