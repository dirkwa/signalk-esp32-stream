#!/usr/bin/env python3
"""
Touch event listener — receives UDP touch packets from the ESP32 and
injects them as mouse events into the Xvfb display using python-xlib
(no subprocess spawn per event — much faster than xdotool).

Usage: python3 touch-listener.py [port] [display]
"""

import socket
import struct
import sys
import os
import time

try:
    from Xlib import X, display, ext
    from Xlib.ext import xtest
    HAS_XLIB = True
except ImportError:
    HAS_XLIB = False

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5005
DISPLAY = sys.argv[2] if len(sys.argv) > 2 else ":99"

EVENT_DOWN = 0
EVENT_MOVE = 1
EVENT_UP = 2


def make_xlib_injector(display_str):
    """Create a fast mouse event injector using python-xlib XTEST extension."""
    os.environ["DISPLAY"] = display_str
    d = display.Display(display_str)
    screen = d.screen()
    root = screen.root

    def inject(x, y, event_type):
        if event_type == EVENT_DOWN:
            # Move then press
            xtest.fake_input(d, X.MotionNotify, x=x, y=y, root=root)
            xtest.fake_input(d, X.ButtonPress, detail=1, root=root)
            d.flush()
        elif event_type == EVENT_MOVE:
            xtest.fake_input(d, X.MotionNotify, x=x, y=y, root=root)
            d.flush()
        elif event_type == EVENT_UP:
            xtest.fake_input(d, X.ButtonRelease, detail=1, root=root)
            d.flush()

    return inject


def make_xdotool_injector(display_str):
    """Fallback: use xdotool via subprocess (slower)."""
    import subprocess
    env = {**os.environ, "DISPLAY": display_str}

    def inject(x, y, event_type):
        try:
            if event_type == EVENT_DOWN:
                subprocess.run(
                    ["xdotool", "mousemove", str(x), str(y), "mousedown", "1"],
                    env=env, timeout=0.2, capture_output=True)
            elif event_type == EVENT_MOVE:
                subprocess.run(
                    ["xdotool", "mousemove", str(x), str(y)],
                    env=env, timeout=0.2, capture_output=True)
            elif event_type == EVENT_UP:
                subprocess.run(
                    ["xdotool", "mouseup", "1"],
                    env=env, timeout=0.2, capture_output=True)
        except subprocess.TimeoutExpired:
            pass

    return inject


def main():
    if HAS_XLIB:
        print(f"Using python-xlib (fast path)", flush=True)
        inject = make_xlib_injector(DISPLAY)
    else:
        print(f"python-xlib not available, falling back to xdotool (slow)",
              flush=True)
        print(f"Install with: pip install python-xlib", flush=True)
        inject = make_xdotool_injector(DISPLAY)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT))
    print(f"Touch listener on UDP :{PORT} → display {DISPLAY}", flush=True)

    count = 0
    event_names = {EVENT_DOWN: "DOWN", EVENT_MOVE: "MOVE", EVENT_UP: "UP"}
    last_log = 0

    while True:
        data, addr = sock.recvfrom(16)
        if len(data) < 5:
            continue

        x = struct.unpack_from("<H", data, 0)[0]
        y = struct.unpack_from("<H", data, 2)[0]
        event_type = data[4]

        inject(x, y, event_type)
        count += 1

        now = time.monotonic()
        if event_type != EVENT_MOVE or now - last_log > 2.0:
            name = event_names.get(event_type, f"?{event_type}")
            print(f"  [{count}] {name} ({x},{y})", flush=True)
            last_log = now


if __name__ == "__main__":
    main()
