#!/bin/bash
# Switch Redmi Buds 8 Pro between Classic (BR/EDR) and Bluetooth LE (LE Audio / BAP)
MAC="B8:53:84:F3:D7:D0"
ACTION="${1:-toggle}"

is_connected() {
    bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes"
}

is_le_connected() {
    bluetoothctl info "$MAC" 2>/dev/null | grep -q "LE.Connected: yes"
}

connect_le() {
    echo "[*] Disconnecting existing connection..."
    bluetoothctl disconnect "$MAC" >/dev/null 2>&1
    sleep 0.8

    echo "[*] Scanning for LE advertisement..."
    bluetoothctl --timeout 3 scan on >/dev/null 2>&1

    echo "[*] Connecting via LE..."
    bluetoothctl connect "$MAC"
}

connect_classic() {
    echo "[*] Disconnecting existing connection..."
    bluetoothctl disconnect "$MAC" >/dev/null 2>&1
    sleep 0.8

    echo "[*] Connecting via Classic Bluetooth (BR/EDR)..."
    bluetoothctl connect "$MAC"
}

case "$ACTION" in
    le|on)
        connect_le
        ;;
    classic|off)
        connect_classic
        ;;
    toggle)
        if is_le_connected; then
            connect_classic
        else
            connect_le
        fi
        ;;
    status)
        if is_le_connected; then
            echo "LE"
        elif is_connected; then
            echo "CLASSIC"
        else
            echo "DISCONNECTED"
        fi
        ;;
    *)
        echo "Usage: $0 {le|classic|toggle|status}"
        exit 1
        ;;
esac
