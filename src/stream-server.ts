import * as net from 'net'

/**
 * TCP server that sends length-prefixed JPEG frames to connected clients.
 *
 * Protocol: [4 bytes uint32 BE frame length][N bytes JPEG data] repeated.
 *
 * The ESP32-P4 client connects here and receives the MJPEG stream.
 */
export class StreamServer {
  private server: net.Server | null = null
  private clients: Set<net.Socket> = new Set()
  private readonly port: number
  private readonly log: (msg: string) => void

  constructor(port: number, log: (msg: string) => void) {
    this.port = port
    this.log = log
  }

  start(): void {
    this.server = net.createServer((socket) => {
      const addr = `${socket.remoteAddress}:${socket.remotePort}`
      this.log(`Stream client connected: ${addr}`)
      this.clients.add(socket)

      socket.on('close', () => {
        this.log(`Stream client disconnected: ${addr}`)
        this.clients.delete(socket)
      })

      socket.on('error', (err) => {
        this.log(`Stream client error (${addr}): ${err.message}`)
        this.clients.delete(socket)
      })
    })

    this.server.listen(this.port, () => {
      this.log(`Stream server listening on TCP port ${this.port}`)
    })

    this.server.on('error', (err) => {
      this.log(`Stream server error: ${err.message}`)
    })
  }

  stop(): void {
    for (const client of this.clients) {
      client.destroy()
    }
    this.clients.clear()
    this.server?.close()
    this.server = null
  }

  /**
   * Send a JPEG frame to all connected clients.
   * Each frame is prefixed with its length as a 4-byte big-endian uint32.
   */
  sendFrame(jpeg: Buffer): void {
    if (this.clients.size === 0) return

    const header = Buffer.alloc(4)
    header.writeUInt32BE(jpeg.length, 0)

    for (const client of this.clients) {
      if (!client.writable) {
        this.clients.delete(client)
        continue
      }
      client.write(header)
      client.write(jpeg)
    }
  }

  get clientCount(): number {
    return this.clients.size
  }
}
