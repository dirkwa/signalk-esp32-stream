#!/usr/bin/env python3
"""
Test MJPEG stream server — generates synthetic JPEG frames and serves them
over TCP using the same length-prefixed protocol the plugin uses.

Usage: python3 test-server.py [port] [fps]

Flow control: sendall blocks naturally when the TCP send buffer is full,
which throttles the server to match the client's consumption rate.
"""

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
FPS = int(sys.argv[2]) if len(sys.argv) > 2 else 15
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5004
QUALITY = 60

frame_count = 0


def generate_frame(n: int) -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    bar_width = 80
    bar_x = (n * 8) % (WIDTH + bar_width) - bar_width
    colors = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255),
        (255, 255, 0), (0, 255, 255), (255, 0, 255),
    ]
    color = colors[n % len(colors)]
    draw.rectangle([bar_x, 0, bar_x + bar_width, HEIGHT], fill=color)

    for x in range(0, WIDTH, 128):
        draw.line([(x, 0), (x, HEIGHT)], fill=(40, 40, 40))
    for y in range(0, HEIGHT, 100):
        draw.line([(0, y), (WIDTH, y)], fill=(40, 40, 40))

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 48)
    except OSError:
        font = ImageFont.load_default()

    draw.text((20, 20), f"Frame {n}", fill=(255, 255, 255), font=font)
    draw.text((20, 80), f"{WIDTH}x{HEIGHT} @ {FPS}fps",
              fill=(180, 180, 180), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=QUALITY)
    return buf.getvalue()


def handle_client(conn: socket.socket, addr):
    global frame_count
    print(f"Client connected: {addr}", flush=True)

    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    sent = 0
    interval = 1.0 / FPS

    try:
        while True:
            t0 = time.monotonic()

            jpeg = generate_frame(frame_count)
            frame_count += 1

            header = struct.pack(">I", len(jpeg))
            # sendall will block if the TCP send buffer is full,
            # naturally throttling us to the client's consumption rate.
            conn.sendall(header + jpeg)
            sent += 1

            if sent % 50 == 0:
                print(f"  Sent {sent} frames to {addr}", flush=True)

            # Sleep for remaining frame interval (minus time spent generating/sending)
            elapsed = time.monotonic() - t0
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    except (BrokenPipeError, ConnectionResetError, OSError) as e:
        print(f"Client {addr} disconnected after {sent} frames: {e}",
              flush=True)
    finally:
        conn.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", PORT))
    server.listen(1)
    print(f"MJPEG test server on TCP port {PORT}", flush=True)
    print(f"  {WIDTH}x{HEIGHT} @ {FPS}fps, quality={QUALITY}", flush=True)

    try:
        # Single-client: serve one connection at a time.
        # When the client disconnects, accept the next.
        while True:
            conn, addr = server.accept()
            handle_client(conn, addr)  # blocks until client disconnects
    except KeyboardInterrupt:
        print("\nShutting down", flush=True)
    finally:
        server.close()


if __name__ == "__main__":
    main()
