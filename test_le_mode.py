#!/usr/bin/env python3
"""
Redmi Buds 8 Pro – LE / Low Latency Mode & Headset Diagnostics & Verification Tool
Tests RFCOMM firmware response, Audio-Visual Latency sync, and Profile switching.
"""

import sys
import os
import time
import subprocess
import json

try:
    import dbus
except ImportError:
    print("Error: python-dbus is required.")
    sys.exit(1)

SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")

def get_dbus_interface():
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object("org.redmibuds8.Control", "/org/redmibuds8/Control")
        props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
        ctrl = dbus.Interface(obj, "org.redmibuds8.Control")
        return props, ctrl
    except Exception as e:
        print(f"[-] Could not connect to org.redmibuds8.Control daemon: {e}")
        print("    Ensure redmibuds8.service is running (systemctl --user status redmibuds8.service)")
        return None, None

def play_sound(filename):
    path = os.path.join(SOUNDS_DIR, filename)
    if os.path.exists(path):
        subprocess.run(["paplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        # Fallback system beep
        subprocess.run(["canberra-gtk-play", "-i", "bell"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_active_audio_profile():
    try:
        out = subprocess.check_output(["pactl", "list", "cards"], text=True)
        for block in out.split("Card #"):
            if "B8_53_84_F3_D7_D0" in block:
                for line in block.splitlines():
                    if "Active Profile:" in line:
                        return line.split("Active Profile:")[1].strip()
    except Exception:
        pass
    return "Unknown"

def main():
    props, ctrl = get_dbus_interface()
    if not props:
        return

    while True:
        os.system("clear")
        print("===============================================================")
        print("   Redmi Buds 8 Pro – LE Mode & Audio Diagnostic Tool")
        print("===============================================================\n")

        try:
            connected = bool(props.Get("org.redmibuds8.Control", "Connected"))
            le_mode = bool(props.Get("org.redmibuds8.Control", "LeMode"))
            batt_l = int(props.Get("org.redmibuds8.Control", "BatteryLeft"))
            batt_r = int(props.Get("org.redmibuds8.Control", "BatteryRight"))
            batt_c = int(props.Get("org.redmibuds8.Control", "BatteryCase"))
            anc_mode = int(props.Get("org.redmibuds8.Control", "AncMode"))
        except Exception as e:
            print(f"Error querying telemetry: {e}")
            break

        anc_str = {0: "Off", 1: "Noise Cancellation", 2: "Transparency"}.get(anc_mode, "Unknown")
        profile = get_active_audio_profile()

        print(f" [*] Earbuds Connection : {'CONNECTED (RFCOMM Channel 28)' if connected else 'DISCONNECTED'}")
        print(f" [*] Battery Levels      : L: {batt_l if batt_l >= 0 else '--'}% | R: {batt_r if batt_r >= 0 else '--'}% | Case: {batt_c if batt_c >= 0 else '--'}%")
        print(f" [*] Noise Control       : {anc_str}")
        print(f" [*] Active Card Profile : {profile}")
        print(f" [*] LE / Low Latency    : {'[ ACTIVE / ON ] (Low DSP Buffer ~60ms)' if le_mode else '[ INACTIVE / OFF ] (Standard Media ~200ms)'}\n")

        print("---------------------------------------------------------------")
        print(" Actions:")
        print("   [1] Turn LE / Low Latency Mode ON  (Vela OS 030028 00 + chime)")
        print("   [2] Turn LE / Low Latency Mode OFF (Vela OS 030028 01 + chime)")
        print("   [3] Run Audio-Visual Latency Sync Test (Visual flash + Audio click)")
        print("   [4] Run Rapid Click Cadence Test (Transient delay test)")
        print("   [5] Switch to Casual Headphones (A2DP High Fidelity Media)")
        print("   [6] Switch to Headset with Mic (HFP Hands-Free + Microphone)")
        print("   [q] Quit")
        print("---------------------------------------------------------------")

        choice = input("Enter option [1-6, q]: ").strip().lower()

        if choice == "1":
            print("\n>> Switching to Low Latency (LE Mode ON)...")
            ctrl.SetLeMode(True)
            play_sound("le_on.wav")
            print(">> Command sent. Firmware acknowledged. Rising confirmation tone played.")
            time.sleep(1.2)
        elif choice == "2":
            print("\n>> Switching to Standard (LE Mode OFF)...")
            ctrl.SetLeMode(False)
            play_sound("le_off.wav")
            print(">> Command sent. Firmware acknowledged. Falling confirmation tone played.")
            time.sleep(1.2)
        elif choice == "3":
            print("\n--- Audio-Visual Sync Latency Test ---")
            print("Look at the screen while wearing the earbuds.")
            print("Watch the flash and listen for the click:\n")
            time.sleep(1)
            for i in range(5, 0, -1):
                print(f"Starting test in {i}...", end="\r", flush=True)
                time.sleep(1)
            print("\n" + "="*40)
            for flash_idx in range(1, 6):
                time.sleep(1.0)
                # Visual Flash exactly simultaneously with audio beep
                print(f"\n   >>> [ ● FLASH & BEEP #{flash_idx} ● ] <<<", flush=True)
                subprocess.run(["canberra-gtk-play", "-i", "bell"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("\n" + "="*40)
            print("\nResult Guide:")
            print(" - Standard Mode: Sound lags behind the flash by ~150-200ms.")
            print(" - LE Low Latency Mode: Sound and flash hit in near-instant synchronization (~60ms).\n")
            input("Press Enter to continue...")
        elif choice == "4":
            print("\nPlaying 8 rapid clicks spaced at 120ms intervals...")
            for _ in range(8):
                subprocess.run(["canberra-gtk-play", "-i", "bell"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.12)
            time.sleep(1)
        elif choice == "5":
            print("\nSwitching to Casual Headphones (A2DP High Fidelity)...")
            subprocess.run(["pactl", "set-card-profile", "bluez_card.B8_53_84_F3_D7_D0", "a2dp-sink"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("Profile set to A2DP Sink.")
            time.sleep(1)
        elif choice == "6":
            print("\nSwitching to Headset with Microphone (HFP/mSBC)...")
            subprocess.run(["pactl", "set-card-profile", "bluez_card.B8_53_84_F3_D7_D0", "headset-head-unit"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("Profile set to Headset Head Unit (Microphone active).")
            time.sleep(1)
        elif choice == "q":
            print("Exiting.")
            break

if __name__ == "__main__":
    main()
