#!/usr/bin/env python3
"""
Touch event listener — receives UDP touch packets from the ESP32 and
injects them as mouse events into the Xvfb display via xdotool.

Usage: python3 touch-listener.py [port] [display]

Packet format (8 bytes, little-endian):
  [2B uint16 X] [2B uint16 Y] [1B event: 0=down,1=move,2=up] [3B padding]
"""

import socket
import struct
import subprocess
import sys
import os

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5005
DISPLAY = sys.argv[2] if len(sys.argv) > 2 else ":99"

EVENT_DOWN = 0
EVENT_MOVE = 1
EVENT_UP = 2

event_names = {EVENT_DOWN: "DOWN", EVENT_MOVE: "MOVE", EVENT_UP: "UP"}


def inject_touch(x, y, event_type):
    env = {**os.environ, "DISPLAY": DISPLAY}
    try:
        if event_type == EVENT_DOWN:
            subprocess.run(
                ["xdotool", "mousemove", str(x), str(y), "mousedown", "1"],
                env=env, timeout=0.5, capture_output=True)
        elif event_type == EVENT_MOVE:
            subprocess.run(
                ["xdotool", "mousemove", str(x), str(y)],
                env=env, timeout=0.5, capture_output=True)
        elif event_type == EVENT_UP:
            subprocess.run(
                ["xdotool", "mouseup", "1"],
                env=env, timeout=0.5, capture_output=True)
    except subprocess.TimeoutExpired:
        pass


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT))
    print(f"Touch listener on UDP port {PORT}, injecting to display {DISPLAY}",
          flush=True)

    count = 0
    while True:
        data, addr = sock.recvfrom(16)
        if len(data) < 5:
            continue

        x = struct.unpack_from("<H", data, 0)[0]
        y = struct.unpack_from("<H", data, 2)[0]
        event_type = data[4]

        count += 1
        if count % 10 == 1 or event_type != EVENT_MOVE:
            name = event_names.get(event_type, f"?{event_type}")
            print(f"  [{count}] {name} ({x}, {y}) from {addr[0]}",
                  flush=True)

        inject_touch(x, y, event_type)


if __name__ == "__main__":
    main()
