#!/usr/bin/env python3
"""
ACK-paced MJPEG test server — protocol v2 for the cockpit stream widget.

Wire format per frame: [4-byte uint32 BE length][JPEG bytes], after which
the server BLOCKS until the client sends a 1-byte ACK. A producer thread
renders frames into a 1-deep "latest" slot, so the client always receives
the newest frame and never a backlog. At most one frame is ever in flight:
this is the esp-hosted-mcu#184 mitigation (sustained unpaced inbound TCP
wedges the P4's C6 SDIO link) and it self-paces the fps to whatever the
panel actually achieves.

This is the phase-0 soak server (no SignalK, no Chromium) and the
reference for the ACK change in stream-server.ts.

Usage: python3 test-server-ack.py [--port 5004] [--fps 20] [--quality 60]
  --fps is the PRODUCER rate ceiling; delivery rate is set by client ACKs.
"""

import argparse
import io
import socket
import struct
import threading
import time
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFont

WIDTH = 1024
HEIGHT = 600
ACK_TIMEOUT_S = 30.0


class LatestFrame:
    """1-deep slot: producer overwrites, consumer takes the newest.
    close() marks the producer dead so waiting consumers unblock."""

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
        the socket ACK timeout does not cover a Condition wait, so without
        this a client would block forever."""
        with self._cond:
            while self._seq <= seq and not self.closed:
                self._cond.wait()
            if self._seq <= seq:
                return None, seq
            return self._jpeg, self._seq


def load_font(size: int):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except OSError:
        return ImageFont.load_default()


FONT = load_font(48)
FONT_SMALL = load_font(28)


def generate_frame(n: int, quality: int) -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    bar_width = 80
    bar_x = (n * 8) % (WIDTH + bar_width) - bar_width
    colors = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255),
        (255, 255, 0), (0, 255, 255), (255, 0, 255),
    ]
    draw.rectangle([bar_x, 0, bar_x + bar_width, HEIGHT],
                   fill=colors[n % len(colors)])

    for x in range(0, WIDTH, 128):
        draw.line([(x, 0), (x, HEIGHT)], fill=(40, 40, 40))
    for y in range(0, HEIGHT, 100):
        draw.line([(0, y), (WIDTH, y)], fill=(40, 40, 40))

    draw.text((20, 20), f"Frame {n}", fill=(255, 255, 255), font=FONT)
    draw.text((20, 80), time.strftime("%H:%M:%S"),
              fill=(180, 180, 180), font=FONT)
    # Corner markers to catch orientation/cropping mistakes on-device later.
    draw.text((20, HEIGHT - 50), "BL", fill=(255, 128, 0), font=FONT_SMALL)
    draw.text((WIDTH - 70, 20), "TR", fill=(0, 255, 128), font=FONT_SMALL)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def producer(slot: LatestFrame, fps: int, quality: int):
    try:
        n = 0
        interval = 1.0 / fps
        while True:
            t0 = time.monotonic()
            slot.publish(generate_frame(n, quality))
            n += 1
            remaining = interval - (time.monotonic() - t0)
            if remaining > 0:
                time.sleep(remaining)
    except Exception:
        # A silently-dead daemon thread looks like a healthy server with a
        # frozen client; make the failure loud and unblock consumers.
        import traceback
        traceback.print_exc()
        slot.close()


def handle_client(conn: socket.socket, addr, slot: LatestFrame):
    print(f"Client connected: {addr}", flush=True)
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn.settimeout(ACK_TIMEOUT_S)

    sent = 0
    sent_bytes = 0
    seq = 0
    t_report = time.monotonic()
    sent_at_report = 0
    bytes_at_report = 0

    try:
        while True:
            jpeg, seq = slot.take_newer_than(seq)
            if jpeg is None:
                print(f"client {addr}: producer gone, dropping", flush=True)
                return
            conn.sendall(struct.pack(">I", len(jpeg)) + jpeg)
            sent += 1
            sent_bytes += len(jpeg) + 4

            ack = conn.recv(1)
            if not ack:
                print(f"Client {addr} closed (EOF)", flush=True)
                return

            now = time.monotonic()
            if now - t_report >= 5.0:
                dt = now - t_report
                fps = (sent - sent_at_report) / dt
                kbs = (sent_bytes - bytes_at_report) / dt / 1024
                print(f"  {addr}: {sent} frames, {fps:.1f} fps, "
                      f"{kbs:.0f} KB/s (ACK-paced)", flush=True)
                t_report, sent_at_report, bytes_at_report = now, sent, sent_bytes

    except socket.timeout:
        print(f"Client {addr}: no ACK in {ACK_TIMEOUT_S}s, dropping "
              f"after {sent} frames", flush=True)
    except (BrokenPipeError, ConnectionResetError, OSError) as e:
        print(f"Client {addr} disconnected after {sent} frames: {e}",
              flush=True)
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5004)
    ap.add_argument("--fps", type=int, default=20,
                    help="producer rate ceiling; delivery is ACK-paced")
    ap.add_argument("--quality", type=int, default=60)
    args = ap.parse_args()
    if args.fps < 1:
        ap.error("--fps must be >= 1")
    if not 1 <= args.quality <= 95:
        ap.error("--quality must be 1..95")

    slot = LatestFrame()
    threading.Thread(target=producer, args=(slot, args.fps, args.quality),
                     daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", args.port))
    server.listen(1)
    print(f"ACK-paced MJPEG test server on TCP port {args.port}", flush=True)
    print(f"  {WIDTH}x{HEIGHT}, producer ceiling {args.fps} fps, "
          f"quality={args.quality}", flush=True)

    try:
        while True:
            conn, addr = server.accept()
            handle_client(conn, addr, slot)
    except KeyboardInterrupt:
        print("\nShutting down", flush=True)
    finally:
        server.close()


if __name__ == "__main__":
    main()
