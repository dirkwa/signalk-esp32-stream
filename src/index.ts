import { Plugin, ServerAPI, Path } from '@signalk/server-api'
import { PluginConfig, defaults, schema } from './config'
import { Xvfb } from './xvfb'
import { Chromium } from './chromium'
import { Encoder } from './encoder'
import { StreamServer } from './stream-server'
import { TouchServer } from './touch-server'

const RESTART_DELAY_MS = 5000

module.exports = (app: ServerAPI): Plugin => {
  let xvfb: Xvfb | null = null
  let chromium: Chromium | null = null
  let encoder: Encoder | null = null
  let streamServer: StreamServer | null = null
  let touchServer: TouchServer | null = null
  let frameCount = 0
  let running = false

  const log = (msg: string) => app.debug(msg)
  const logError = (msg: string) => app.error(msg)

  const plugin: Plugin = {
    id: 'signalk-esp32-stream',
    name: 'ESP32 Display Stream',
    description:
      'Stream KIP dashboard to an ESP32-P4 display via MJPEG over TCP',

    start: async (config: PluginConfig) => {
      const cfg = { ...defaults, ...config }
      running = true
      frameCount = 0

      try {
        // 1. Stream server — start first so clients can connect while we set up
        streamServer = new StreamServer(cfg.streamPort, log)
        streamServer.start()

        // 2. Touch server
        touchServer = new TouchServer(cfg.touchPort, cfg.display, log)
        touchServer.start()

        // 3. Xvfb
        xvfb = new Xvfb(cfg.display, cfg.resolution, log)
        await xvfb.start()

        // 4. Chromium
        chromium = new Chromium(cfg.display, cfg.kipUrl, cfg.chromiumBin, log)
        await chromium.start()

        // 5. Encoder — pipes JPEG frames to the stream server
        encoder = new Encoder(
          cfg.display,
          cfg.resolution,
          cfg.framerate,
          cfg.jpegQuality,
          log,
        )
        encoder.start((jpeg) => {
          frameCount++
          streamServer?.sendFrame(jpeg)
        })

        updateStatus('streaming')
        log(
          `Plugin started: ${cfg.resolution} @ ${cfg.framerate}fps, ` +
            `quality=${cfg.jpegQuality}, stream=:${cfg.streamPort}, ` +
            `touch=:${cfg.touchPort}`,
        )
      } catch (err: any) {
        logError(`Startup failed: ${err.message}`)
        updateStatus(`error: ${err.message}`)
        stopAll()
      }
    },

    stop: () => {
      running = false
      stopAll()
      updateStatus('stopped')
      log('Plugin stopped')
    },

    schema: () => schema,

    statusMessage: () => {
      if (!running) return 'Stopped'
      const clients = streamServer?.clientCount ?? 0
      return `Streaming — ${frameCount} frames sent, ${clients} client(s)`
    },
  }

  function stopAll(): void {
    encoder?.stop()
    encoder = null
    chromium?.stop()
    chromium = null
    xvfb?.stop()
    xvfb = null
    touchServer?.stop()
    touchServer = null
    streamServer?.stop()
    streamServer = null
  }

  function updateStatus(status: string): void {
    app.handleMessage(plugin.id, {
      updates: [
        {
          values: [
            {
              path: 'plugins.esp32stream.status' as Path,
              value: status,
            },
          ],
        },
      ],
    })
  }

  return plugin
}
