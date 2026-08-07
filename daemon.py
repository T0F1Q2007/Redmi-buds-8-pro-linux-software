import socket
import logging
import signal
import time
from threading import Thread
import traceback

from dasbus.connection import SessionMessageBus
from dasbus.server.interface import dbus_interface, dbus_signal
from dasbus.typing import Int, Bool, Str
from dasbus.loop import EventLoop
from gi.repository import GLib

MAC_ADDRESS = "B8:53:84:F3:D7:D0"
PORT = 28
DBUS_SERVICE = "org.redmibuds8.Control"
DBUS_PATH = "/org/redmibuds8/Control"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("redmibuds8")

class BudsConnection:
    def __init__(self):
        self.sock = None
        self.seq = 0
        self.connected = False

    def connect(self):
        while True:
            try:
                log.info(f"Trying to connect to {MAC_ADDRESS}:{PORT}...")
                s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                s.connect((MAC_ADDRESS, PORT))
                self.sock = s
                self.connected = True
                log.info("Connected to earbuds RFCOMM successfully.")
                self.listen_loop()
            except Exception as e:
                self.connected = False
                if self.sock:
                    try:
                        self.sock.close()
                    except:
                        pass
                self.sock = None
                log.warning(f"Connection failed: {e}. Retrying in 5 seconds...")
                time.sleep(5)

    def listen_loop(self):
        while self.connected:
            try:
                data = self.sock.recv(1024)
                if not data:
                    break
                # Here we could parse battery status from notifications
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
        length = len(payload_hex) // 2 + 1
        cmd_hex = f"fedcbac4{svc_hex}{length:02x}{self.seq:02x}{payload_hex}ef"
        cmd_bytes = bytes.fromhex(cmd_hex)
        
        try:
            self.sock.send(cmd_bytes)
            log.info(f"Sent: {cmd_hex}")
            return True
        except Exception as e:
            log.warning(f"Failed to send command: {e}")
            self.connected = False
            return False

@dbus_interface(DBUS_SERVICE)
class BudsInterface:
    def __init__(self, connection: BudsConnection):
        self.conn = connection

    @dbus_signal
    def StatusChanged(self):
        pass

    def SetAncMode(self, mode: Int):
        # 0: Off, 1: ANC On, 2: Transparency
        log.info(f"DBus call: SetAncMode({mode})")
        self.conn.send_cmd("0800", f"0204{mode:02x}")

    def SetEqMode(self, mode: Int):
        # 1: Standard, 2: Music, 3: Video, 4: Game, 5: Audio Books
        log.info(f"DBus call: SetEqMode({mode})")
        self.conn.send_cmd("f200", f"04003601{mode:02x}")

    def SetImmersiveCommute(self, mode: Int):
        # 0: Off, 1: Train, 2: Transit, 3: Airplane
        log.info(f"DBus call: SetImmersiveCommute({mode})")
        self.conn.send_cmd("f200", f"030067{mode:02x}")

    def SetInEarDetection(self, enabled: Bool):
        log.info(f"DBus call: SetInEarDetection({enabled})")
        mode = 1 if enabled else 0
        self.conn.send_cmd("0800", f"0206{mode:02x}")

    def SetHeadTracking(self, enabled: Bool):
        log.info(f"DBus call: SetHeadTracking({enabled})")
        mode = 1 if enabled else 0
        self.conn.send_cmd("f200", f"030068{mode:02x}")
        
    def SetAudioMode(self, dolby: Bool):
        log.info(f"DBus call: SetAudioMode({dolby})")
        mode = 0x0a if dolby else 0x0b
        self.conn.send_cmd("f200", f"03001d{mode:02x}")

    @property
    def Connected(self) -> Bool:
        return self.conn.connected

def main():
    conn = BudsConnection()
    conn_thread = Thread(target=conn.connect, daemon=True)
    conn_thread.start()

    bus = SessionMessageBus()
    interface = BudsInterface(conn)
    bus.publish_object(DBUS_PATH, interface)
    bus.register_service(DBUS_SERVICE)
    log.info(f"D-Bus service registered as {DBUS_SERVICE}")

    loop = EventLoop()

    def on_shutdown(*_):
        log.info("Shutting down.")
        loop.quit()

    signal.signal(signal.SIGTERM, on_shutdown)
    signal.signal(signal.SIGINT,  on_shutdown)

    loop.run()
    bus.disconnect()

if __name__ == "__main__":
    main()
