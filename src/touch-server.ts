import * as dgram from 'dgram'
import { execSync } from 'child_process'

const EVENT_DOWN = 0
const EVENT_MOVE = 1
const EVENT_UP = 2

/**
 * UDP server that receives 8-byte touch event packets from the ESP32-P4
 * and injects them as mouse events into the Xvfb display via xdotool.
 *
 * Packet format (little-endian):
 *   [2B: uint16 X] [2B: uint16 Y] [1B: event type] [3B: padding]
 */
export class TouchServer {
  private socket: dgram.Socket | null = null
  private readonly port: number
  private readonly display: string
  private readonly log: (msg: string) => void
  private mouseDown = false

  constructor(port: number, display: string, log: (msg: string) => void) {
    this.port = port
    this.display = display
    this.log = log
  }

  start(): void {
    this.socket = dgram.createSocket('udp4')

    this.socket.on('message', (msg) => {
      if (msg.length < 5) return

      const x = msg.readUInt16LE(0)
      const y = msg.readUInt16LE(2)
      const event = msg[4]

      this.handleTouch(x, y, event)
    })

    this.socket.on('error', (err) => {
      this.log(`Touch server error: ${err.message}`)
    })

    this.socket.bind(this.port, () => {
      this.log(`Touch server listening on UDP port ${this.port}`)
    })
  }

  stop(): void {
    this.socket?.close()
    this.socket = null
  }

  private handleTouch(x: number, y: number, event: number): void {
    const env = { ...process.env, DISPLAY: this.display }

    try {
      switch (event) {
        case EVENT_DOWN:
          execSync(`xdotool mousemove ${x} ${y} mousedown 1`, { env, timeout: 500 })
          this.mouseDown = true
          break
        case EVENT_MOVE:
          if (this.mouseDown) {
            execSync(`xdotool mousemove ${x} ${y}`, { env, timeout: 500 })
          }
          break
        case EVENT_UP:
          execSync(`xdotool mouseup 1`, { env, timeout: 500 })
          this.mouseDown = false
          break
      }
    } catch (err: any) {
      this.log(`Touch inject error: ${err.message}`)
    }
  }
}
