#!/usr/bin/env python3
"""Touch listener using xdotool (Popen, no wait — fire and forget)."""
import socket, struct, subprocess, os, sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5005
DISPLAY = sys.argv[2] if len(sys.argv) > 2 else ":99"
env = {**os.environ, "DISPLAY": DISPLAY}

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", PORT))
print(f"Touch (xdotool) on UDP :{PORT} → {DISPLAY}", flush=True)

count = 0
names = {0: "DOWN", 1: "MOVE", 2: "UP"}
while True:
    data, addr = sock.recvfrom(16)
    if len(data) < 5:
        continue
    x = struct.unpack_from("<H", data, 0)[0]
    y = struct.unpack_from("<H", data, 2)[0]
    ev = data[4]
    count += 1
    if ev == 0:
        subprocess.Popen(["xdotool", "mousemove", str(x), str(y), "mousedown", "1"], env=env)
    elif ev == 1:
        subprocess.Popen(["xdotool", "mousemove", str(x), str(y)], env=env)
    elif ev == 2:
        subprocess.Popen(["xdotool", "mouseup", "1"], env=env)
    if ev != 1 or count % 20 == 0:
        print(f"  [{count}] {names.get(ev,'?')} ({x},{y})", flush=True)
