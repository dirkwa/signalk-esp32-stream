#!/usr/bin/env python3
"""
Status display server — renders a live dashboard as JPEG frames from
SignalK data and streams to the ESP32 display. No browser needed.

Usage: python3 status-display.py [port] [fps] [signalk_host]
"""

import io
import json
import socket
import struct
import sys
import time
import urllib.request

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFont

WIDTH = 1024
HEIGHT = 600
FPS = int(sys.argv[2]) if len(sys.argv) > 2 else 2
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5004
SK_HOST = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:3000"
QUALITY = 70

# Colors
BG = (20, 25, 35)
PANEL_BG = (30, 38, 50)
LABEL_COLOR = (120, 140, 160)
VALUE_COLOR = (220, 240, 255)
UNIT_COLOR = (80, 100, 120)
GREEN = (40, 200, 80)
RED = (220, 60, 60)
YELLOW = (220, 200, 40)
BLUE = (60, 140, 220)
SEPARATOR = (50, 60, 75)

# Fonts
try:
    FONT_LARGE = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
    FONT_MEDIUM = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    FONT_SMALL = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    FONT_LABEL = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
except OSError:
    FONT_LARGE = ImageFont.load_default()
    FONT_MEDIUM = FONT_LARGE
    FONT_SMALL = FONT_LARGE
    FONT_LABEL = FONT_LARGE


def fetch_signalk():
    """Fetch current vessel data from SignalK API."""
    try:
        url = f"{SK_HOST}/signalk/v1/api/vessels/self"
        with urllib.request.urlopen(url, timeout=2) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def get_value(data, path, default=None):
    """Navigate a nested dict by dot-separated path."""
    if data is None:
        return default
    parts = path.split(".")
    node = data
    for p in parts:
        if isinstance(node, dict) and p in node:
            node = node[p]
        else:
            return default
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def rad_to_deg(val):
    if val is None:
        return None
    return val * 180.0 / 3.14159265


def ms_to_knots(val):
    if val is None:
        return None
    return val * 1.94384


def kelvin_to_c(val):
    if val is None:
        return None
    return val - 273.15


def pa_to_hpa(val):
    if val is None:
        return None
    return val / 100.0


def fmt(val, decimals=1, fallback="---"):
    if val is None:
        return fallback
    return f"{val:.{decimals}f}"


def draw_gauge(draw, x, y, w, h, label, value_str, unit="", color=VALUE_COLOR):
    """Draw a single gauge panel."""
    draw.rectangle([x, y, x + w, y + h], fill=PANEL_BG, outline=SEPARATOR)
    draw.text((x + 8, y + 4), label, fill=LABEL_COLOR, font=FONT_LABEL)
    draw.text((x + 8, y + 24), value_str, fill=color, font=FONT_LARGE)
    if unit:
        draw.text((x + 8, y + h - 24), unit, fill=UNIT_COLOR, font=FONT_SMALL)


def render_frame(data, frame_n):
    """Render a status display frame."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle([0, 0, WIDTH, 40], fill=(25, 32, 45))
    draw.text((10, 6), "Signal K Cockpit", fill=VALUE_COLOR, font=FONT_MEDIUM)
    t = time.strftime("%H:%M:%S")
    draw.text((WIDTH - 120, 10), t, fill=LABEL_COLOR, font=FONT_SMALL)

    # Extract navigation data
    cog = rad_to_deg(get_value(data, "navigation.courseOverGroundTrue"))
    sog = ms_to_knots(get_value(data, "navigation.speedOverGround"))
    hdg = rad_to_deg(get_value(data, "navigation.headingTrue"))
    stw = ms_to_knots(get_value(data, "navigation.speedThroughWater"))
    depth = get_value(data, "environment.depth.belowTransducer")
    wind_speed = ms_to_knots(
        get_value(data, "environment.wind.speedApparent"))
    wind_angle = rad_to_deg(
        get_value(data, "environment.wind.angleApparent"))
    temp_water = kelvin_to_c(
        get_value(data, "environment.water.temperature"))
    pressure = pa_to_hpa(
        get_value(data, "environment.outside.pressure"))
    temp_air = kelvin_to_c(
        get_value(data, "environment.outside.temperature"))
    lat = get_value(data, "navigation.position.latitude")
    lon = get_value(data, "navigation.position.longitude")

    # Row 1: Navigation (y=50)
    gw = (WIDTH - 40) // 4  # gauge width
    gh = 100
    y0 = 50
    draw_gauge(draw, 10, y0, gw, gh, "COG", f"{fmt(cog, 0)}°", "degrees",
               GREEN if cog is not None else LABEL_COLOR)
    draw_gauge(draw, 20 + gw, y0, gw, gh, "SOG", fmt(sog, 1), "knots",
               GREEN if sog is not None else LABEL_COLOR)
    draw_gauge(draw, 30 + gw * 2, y0, gw, gh, "HDG", f"{fmt(hdg, 0)}°",
               "degrees", BLUE if hdg is not None else LABEL_COLOR)
    draw_gauge(draw, 40 + gw * 3, y0, gw - 20, gh, "STW", fmt(stw, 1),
               "knots", BLUE if stw is not None else LABEL_COLOR)

    # Row 2: Environment (y=160)
    y1 = 160
    draw_gauge(draw, 10, y1, gw, gh, "DEPTH", fmt(depth, 1), "meters",
               RED if depth is not None and depth < 3 else VALUE_COLOR)
    draw_gauge(draw, 20 + gw, y1, gw, gh, "WIND SPD",
               fmt(wind_speed, 1), "knots",
               YELLOW if wind_speed is not None else LABEL_COLOR)
    draw_gauge(draw, 30 + gw * 2, y1, gw, gh, "WIND ANG",
               f"{fmt(wind_angle, 0)}°", "apparent",
               YELLOW if wind_angle is not None else LABEL_COLOR)
    draw_gauge(draw, 40 + gw * 3, y1, gw - 20, gh, "PRESSURE",
               fmt(pressure, 0), "hPa")

    # Row 3: Temperature + Position (y=270)
    y2 = 270
    draw_gauge(draw, 10, y2, gw, gh, "WATER TEMP",
               f"{fmt(temp_water, 1)}°C", "",
               BLUE if temp_water is not None else LABEL_COLOR)
    draw_gauge(draw, 20 + gw, y2, gw, gh, "AIR TEMP",
               f"{fmt(temp_air, 1)}°C", "")

    # Position panel (wider)
    pw = gw * 2 - 10
    draw.rectangle([30 + gw * 2, y2, 30 + gw * 2 + pw, y2 + gh],
                   fill=PANEL_BG, outline=SEPARATOR)
    draw.text((38 + gw * 2, y2 + 4), "POSITION", fill=LABEL_COLOR,
              font=FONT_LABEL)
    if lat is not None and lon is not None:
        lat_str = f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}"
        lon_str = f"{abs(lon):.5f}° {'E' if lon >= 0 else 'W'}"
        draw.text((38 + gw * 2, y2 + 24), lat_str, fill=VALUE_COLOR,
                  font=FONT_MEDIUM)
        draw.text((38 + gw * 2, y2 + 58), lon_str, fill=VALUE_COLOR,
                  font=FONT_MEDIUM)
    else:
        draw.text((38 + gw * 2, y2 + 30), "No fix", fill=RED,
                  font=FONT_LARGE)

    # Row 4: System status (y=380)
    y3 = 385
    draw.rectangle([10, y3, WIDTH - 10, y3 + 30], fill=(25, 32, 45))
    draw.text((15, y3 + 4), "System Status", fill=LABEL_COLOR,
              font=FONT_SMALL)

    # Status indicators
    y4 = 420
    indicators = [
        ("WiFi", GREEN, "Connected"),
        ("SignalK", GREEN if data else RED,
         "OK" if data else "Offline"),
        ("N2K", LABEL_COLOR, "Port 2599"),
        ("BLE", LABEL_COLOR, "Pending"),
        ("Display", GREEN, f"Frame {frame_n}"),
    ]
    ix = 10
    for name, color, status in indicators:
        # Status dot
        draw.ellipse([ix, y4 + 6, ix + 12, y4 + 18], fill=color)
        draw.text((ix + 18, y4 + 2), f"{name}: {status}",
                  fill=LABEL_COLOR, font=FONT_LABEL)
        ix += (WIDTH - 20) // len(indicators)

    # Encode to JPEG
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=QUALITY, subsampling="4:2:0")
    return buf.getvalue()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", PORT))
    server.listen(1)
    print(f"Status display on TCP :{PORT} @ {FPS}fps", flush=True)
    print(f"SignalK: {SK_HOST}", flush=True)

    frame_n = 0
    try:
        while True:
            print("Waiting for ESP32...", flush=True)
            conn, addr = server.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"Client: {addr}", flush=True)

            try:
                while True:
                    data = fetch_signalk()
                    jpeg = render_frame(data, frame_n)
                    frame_n += 1

                    header = struct.pack(">I", len(jpeg))
                    conn.sendall(header + jpeg)

                    time.sleep(1.0 / FPS)
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                print(f"Disconnected: {e}", flush=True)
            finally:
                conn.close()
    except KeyboardInterrupt:
        print("\nDone", flush=True)
    finally:
        server.close()


if __name__ == "__main__":
    main()
