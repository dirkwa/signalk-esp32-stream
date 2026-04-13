#!/usr/bin/env python3
"""
Real KIP streaming server. Captures Chromium (KIP) on Xvfb via ffmpeg,
streams length-prefixed JPEG frames over TCP to the ESP32.

Usage: python3 stream-kip.py [port] [fps] [quality]

Assumes Xvfb :99 and Chromium are already running.
"""

import socket
import struct
import subprocess
import sys
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5004
FPS = int(sys.argv[2]) if len(sys.argv) > 2 else 10
QUALITY = int(sys.argv[3]) if len(sys.argv) > 3 else 5
DISPLAY = ":99"
RESOLUTION = "1024x600"

JPEG_SOI = b'\xff\xd8'
JPEG_EOI = b'\xff\xd9'


def find_jpeg_frames(stream):
    """Generator that yields complete JPEG frames from an image2pipe stream."""
    import os
    buf = b''
    fd = stream.fileno()
    while True:
        # Read whatever is available (up to 65536 bytes)
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        while True:
            # Find SOI
            soi = buf.find(JPEG_SOI)
            if soi < 0:
                buf = b''
                break
            if soi > 0:
                buf = buf[soi:]

            # Find EOI (search past the SOI marker)
            eoi = buf.find(JPEG_EOI, 2)
            if eoi < 0:
                break  # incomplete frame, wait for more data

            # Extract complete JPEG
            frame_end = eoi + 2
            yield buf[:frame_end]
            buf = buf[frame_end:]


def main():
    # Start ffmpeg
    cmd = [
        'ffmpeg',
        '-f', 'x11grab',
        '-r', str(FPS),
        '-s', RESOLUTION,
        '-i', DISPLAY,
        '-pix_fmt', 'yuvj420p',     # YUV 4:2:0 — required by ESP32-P4 HW JPEG decoder
        '-vcodec', 'mjpeg',
        '-q:v', str(QUALITY),
        '-huffman', 'default',       # baseline Huffman (not optimized/progressive)
        '-f', 'image2pipe',
        '-an',
        'pipe:1',
    ]
    print(f"Starting ffmpeg: {' '.join(cmd)}", flush=True)
    ffmpeg = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)

    # TCP server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", PORT))
    server.listen(1)
    print(f"Listening on TCP port {PORT} ({RESOLUTION} @ {FPS}fps, q={QUALITY})",
          flush=True)

    try:
        while True:
            print("Waiting for client...", flush=True)
            conn, addr = server.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"Client connected: {addr}", flush=True)

            sent = 0
            try:
                for jpeg in find_jpeg_frames(ffmpeg.stdout):
                    header = struct.pack(">I", len(jpeg))
                    conn.sendall(header + jpeg)
                    sent += 1
                    if sent % 50 == 0:
                        print(f"  Sent {sent} frames ({len(jpeg)} bytes last)",
                              flush=True)
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                print(f"Client {addr} disconnected after {sent} frames: {e}",
                      flush=True)
            finally:
                conn.close()

    except KeyboardInterrupt:
        print("\nShutting down", flush=True)
    finally:
        ffmpeg.terminate()
        server.close()


if __name__ == "__main__":
    main()
