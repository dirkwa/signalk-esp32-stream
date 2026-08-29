#!/usr/bin/env python3
"""
ACK-paced capture server — protocol v2 for the cockpit "stream" widget.

Supervises the whole capture chain in one process:
  Xvfb :99  ->  Chromium kiosk (Freeboard/KIP/any URL)  ->  ffmpeg x11grab
  -> latest-frame slot -> TCP :5004 ([u32 BE len][JPEG], wait 1-byte ACK)
and injects UDP :5005 touch packets into the X display via XTEST.

The ACK gate sends only the NEWEST frame after each client ACK, so at most
one frame is in flight (esp-hosted-mcu#184 mitigation) and the panel paces
its own fps. Touch packets: LE u16 x, u16 y, u8 type (0 down/1 move/2 up).

Usage:
  python3 capture-server-ack.py \
      [--url http://localhost:80/@signalk/freeboard-sk/] \
      [--port 5004] [--touch-port 5005] [--fps 15] [--quality 6] \
      [--display :99]

This is the phase-1 dev server and the reference for the plugin's TS port.
"""

import argparse
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

WIDTH, HEIGHT = 1024, 600
ACK_TIMEOUT_S = 30.0
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


class LatestFrame:
    """1-deep slot. close() marks the producer dead so consumers unblock."""

    def __init__(self):
        self._cond = threading.Condition()
        self._jpeg = None
        self._seq = 0
        self.closed = False

    def publish(self, jpeg: bytes):
        with self._cond:
            self._jpeg = jpeg
            self._seq += 1
            self._cond.notify_all()

    def close(self):
        with self._cond:
            self.closed = True
            self._cond.notify_all()

    def take_newer_than(self, seq: int):
        """Newest (jpeg, seq), or (None, seq) once the producer is gone —
        without this a client would block in wait() forever (the socket
        ACK timeout does not cover a Condition wait)."""
        with self._cond:
            while self._seq <= seq and not self.closed:
                self._cond.wait()
            if self._seq <= seq:
                return None, seq
            return self._jpeg, self._seq


def start_xvfb(display: str):
    p = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", f"{WIDTH}x{HEIGHT}x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lock = f"/tmp/.X{display.lstrip(':')}-lock"
    for _ in range(50):
        if os.path.exists(lock):
            return p
        time.sleep(0.1)
    return p  # keep going; chromium will fail loudly if X never came up


def start_chromium(display: str, url: str):
    binary = shutil.which("chromium") or shutil.which("chromium-browser")
    if not binary:
        sys.exit("no chromium binary found")
    env = {**os.environ, "DISPLAY": display}
    profile = os.path.expanduser("~/dev/tmp/chromium-stream-profile")
    return subprocess.Popen(
        [binary, "--kiosk", "--no-sandbox", "--disable-gpu",
         f"--window-size={WIDTH},{HEIGHT}", "--window-position=0,0",
         "--no-first-run", "--disable-infobars", "--hide-scrollbars",
         f"--user-data-dir={profile}", url],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_ffmpeg(display: str, fps: int, quality: int):
    cmd = [
        "ffmpeg",
        "-loglevel", "error",  # quiet, but capture-chain failures stay visible
        "-probesize", "32",
        "-fflags", "nobuffer",
        "-f", "x11grab",
        "-framerate", str(fps),
        "-s", f"{WIDTH}x{HEIGHT}",
        "-draw_mouse", "0",
        "-i", display,
        "-pix_fmt", "yuvj420p",  # 4:2:0 baseline — what the P4 HW decoder wants
        "-vcodec", "mjpeg",
        "-q:v", str(quality),
        "-huffman", "default",
        "-f", "image2pipe",
        "-an",
        "-flush_packets", "1",
        "pipe:1",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE)  # stderr inherited


def frame_reader(ffmpeg, slot: LatestFrame):
    """Drain ffmpeg stdout continuously; keep only the newest complete JPEG."""
    fd = ffmpeg.stdout.fileno()
    buf = b""
    while True:
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        while True:
            soi = buf.find(JPEG_SOI)
            if soi < 0:
                # A chunk may end mid-marker: keep a trailing 0xFF, it can be
                # the first byte of the next SOI.
                buf = buf[-1:] if buf.endswith(b"\xff") else b""
                break
            if soi > 0:
                buf = buf[soi:]
            eoi = buf.find(JPEG_EOI, 2)
            if eoi < 0:
                break
            slot.publish(buf[:eoi + 2])
            buf = buf[eoi + 2:]
    print("capture chain ended (ffmpeg stdout closed)", flush=True)
    slot.close()  # unblock any client waiting on the next frame


# IP of the currently-connected stream client; touch packets from anyone
# else are dropped. XTEST drives the kiosk UI, so an open UDP port would
# hand control of the plotter to any host on the network — tying it to the
# active stream connection needs no configuration and no shared secret.
allowed_touch_ip = None
allowed_touch_lock = threading.Lock()


def touch_injector(display_str: str, port: int):
    from Xlib import X, display as xdisplay
    from Xlib.ext import xtest
    os.environ["DISPLAY"] = display_str
    d = xdisplay.Display(display_str)
    root = d.screen().root

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", port))
    print(f"touch injector on UDP {port} -> {display_str} "
          f"(stream client only)", flush=True)
    while True:
        data, src = s.recvfrom(64)
        with allowed_touch_lock:
            allowed = allowed_touch_ip
        if allowed is None or src[0] != allowed:
            continue
        if len(data) < 5:
            continue
        x, y = struct.unpack("<HH", data[:4])
        t = data[4]
        if t == 0:
            xtest.fake_input(d, X.MotionNotify, x=x, y=y, root=root)
            xtest.fake_input(d, X.ButtonPress, detail=1, root=root)
        elif t == 1:
            xtest.fake_input(d, X.MotionNotify, x=x, y=y, root=root)
        else:
            xtest.fake_input(d, X.ButtonRelease, detail=1, root=root)
        d.flush()


def handle_client(conn: socket.socket, addr, slot: LatestFrame):
    global allowed_touch_ip
    print(f"client connected: {addr}", flush=True)
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn.settimeout(ACK_TIMEOUT_S)
    with allowed_touch_lock:
        allowed_touch_ip = addr[0]
    sent = 0
    sent_bytes = 0
    seq = 0
    t_report = time.monotonic()
    s_report = b_report = 0
    try:
        while True:
            jpeg, seq = slot.take_newer_than(seq)
            if jpeg is None:
                print(f"client {addr}: capture chain gone, dropping", flush=True)
                return
            conn.sendall(struct.pack(">I", len(jpeg)) + jpeg)
            sent += 1
            sent_bytes += len(jpeg) + 4
            if not conn.recv(1):
                print(f"client {addr} closed (EOF)", flush=True)
                return
            now = time.monotonic()
            if now - t_report >= 5.0:
                dt = now - t_report
                print(f"  {addr}: {sent} frames, {(sent - s_report)/dt:.1f} fps, "
                      f"{(sent_bytes - b_report)/dt/1024:.0f} KB/s", flush=True)
                t_report, s_report, b_report = now, sent, sent_bytes
    except socket.timeout:
        print(f"client {addr}: no ACK in {ACK_TIMEOUT_S}s, dropping after {sent}",
              flush=True)
    except (BrokenPipeError, ConnectionResetError, OSError) as e:
        print(f"client {addr} disconnected after {sent} frames: {e}", flush=True)
    finally:
        with allowed_touch_lock:
            allowed_touch_ip = None
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:80/@signalk/freeboard-sk/")
    ap.add_argument("--port", type=int, default=5004)
    ap.add_argument("--touch-port", type=int, default=5005)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--quality", type=int, default=6)
    ap.add_argument("--display", default=":99")
    args = ap.parse_args()
    if args.fps < 1:
        ap.error("--fps must be >= 1")
    if not 2 <= args.quality <= 31:
        ap.error("--quality must be 2..31 (ffmpeg -q:v, lower is better)")

    children = []
    try:
        print(f"Xvfb {args.display} {WIDTH}x{HEIGHT}", flush=True)
        children.append(start_xvfb(args.display))
        time.sleep(1)
        print(f"chromium kiosk -> {args.url}", flush=True)
        children.append(start_chromium(args.display, args.url))
        time.sleep(3)  # let first paint happen before grabbing
        print(f"ffmpeg x11grab {args.fps} fps q{args.quality}", flush=True)
        ffmpeg = start_ffmpeg(args.display, args.fps, args.quality)
        children.append(ffmpeg)

        slot = LatestFrame()
        threading.Thread(target=frame_reader, args=(ffmpeg, slot), daemon=True).start()
        threading.Thread(target=touch_injector, args=(args.display, args.touch_port),
                         daemon=True).start()

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", args.port))
        server.listen(1)
        print(f"ACK-paced MJPEG on TCP {args.port}", flush=True)
        while not slot.closed:
            conn, addr = server.accept()
            handle_client(conn, addr, slot)
        # Dead capture chain: exit non-zero so a supervisor restarts the
        # whole stack instead of the server sitting there looking healthy.
        print("exiting: capture chain is dead", flush=True)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    finally:
        # terminate() alone can leave Xvfb holding /tmp/.X<n>-lock, which
        # makes the next start_xvfb() adopt a display it never owned.
        for p in reversed(children):
            try:
                p.terminate()
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=3)
            except Exception:
                pass


if __name__ == "__main__":
    main()
