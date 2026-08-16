# signalk-esp32-stream

Signal K plugin that streams a browser-rendered dashboard to an ESP32-P4
display as MJPEG over TCP, and feeds touch events back the other way.

```
Xvfb :99  →  Chromium (KIP / app-dock)  →  ffmpeg MJPEG  →  TCP :5004  →  ESP32-P4
                                    touch events  ←  TCP :5005  ←
```

The display device needs no browser and no Signal K client of its own — it
receives JPEG frames and sends back touch coordinates, so a cheap panel can act
as a dashboard for a server running elsewhere on the boat.

## How it works

The plugin supervises four processes and restarts the chain if any of them
exits:

| Piece | Role |
| --- | --- |
| `xvfb.ts` | Headless X display (`:99` by default) for Chromium to draw into |
| `chromium.ts` | Renders the configured dashboard URL at the target resolution |
| `encoder.ts` | ffmpeg, X11 grab → MJPEG at the configured quality/framerate |
| `stream-server.ts` | TCP server that fans frames out to connected displays |
| `touch-server.ts` | TCP server that receives touch coordinates from the display |

## Configuration

| Setting | Default | Notes |
| --- | --- | --- |
| `kipUrl` | `http://…:3000/@signalk/app-dock/` | Dashboard to render |
| `display` | `:99` | Xvfb display number |
| `resolution` | `1024x600x24` | Match the panel |
| `streamPort` | `5004` | MJPEG out |
| `touchPort` | `5005` | Touch in |
| `jpegQuality` | `5` | ffmpeg `-q:v`; lower is better quality |
| `framerate` | `15` | Frames per second |
| `chromiumBin` | `chromium-browser` | Binary name or path |

## Requirements

`Xvfb`, `chromium` (or `chromium-browser`) and `ffmpeg` must be installed on
the Signal K host. The plugin spawns them; it does not bundle them.

## Helper scripts

The `*.py` files at the repo root are development and bring-up aids, not part
of the plugin: a standalone test server, a native status display that renders
Signal K values to JPEG without a browser, and two touch-listener variants.
They are excluded from the published package.

## Status

Early. Working end to end against an ESP32-P4 panel, but rough: no automated
tests, no CI, and configuration is by hand.

## License

signalk-esp32-stream is **source available, not open source**.
See [LICENSE.md](LICENSE.md).

**You may**, free of charge: run it on your own boat or fleet, private or
commercial; use it for internal company operations; modify it for your own use;
use it in education and research; and provide professional services around it.

**You may not**: redistribute it, or publish a modified version of it to npm or
anywhere else. Verbatim copies of official releases may be mirrored and cached.
