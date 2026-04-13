import { ChildProcess, spawn } from 'child_process'

const JPEG_SOI = 0xffd8
const JPEG_EOI = 0xffd9

export type FrameCallback = (jpeg: Buffer) => void

/**
 * Captures the Xvfb display with ffmpeg, encoding to MJPEG.
 * Extracts individual JPEG frames from the image2pipe output and
 * delivers them via callback.
 */
export class Encoder {
  private process: ChildProcess | null = null
  private readonly display: string
  private readonly framerate: number
  private readonly quality: number
  private readonly resolution: string
  private readonly log: (msg: string) => void
  private onFrame: FrameCallback | null = null

  private buf = Buffer.alloc(0)

  constructor(
    display: string,
    resolution: string,
    framerate: number,
    quality: number,
    log: (msg: string) => void,
  ) {
    this.display = display
    this.resolution = resolution.split('x').slice(0, 2).join('x') // strip depth
    this.framerate = framerate
    this.quality = quality
    this.log = log
  }

  start(onFrame: FrameCallback): void {
    this.onFrame = onFrame

    this.process = spawn('ffmpeg', [
      '-f', 'x11grab',
      '-r', String(this.framerate),
      '-s', this.resolution,
      '-i', this.display,
      '-vcodec', 'mjpeg',
      '-q:v', String(this.quality),
      '-f', 'image2pipe',
      '-an',
      'pipe:1',
    ], {
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    this.process.stdout!.on('data', (chunk: Buffer) => {
      this.feed(chunk)
    })

    this.process.stderr?.on('data', (data: Buffer) => {
      const line = data.toString().trim()
      // ffmpeg sends progress info to stderr — only log errors
      if (line.includes('Error') || line.includes('error') || line.includes('Invalid')) {
        this.log(`ffmpeg: ${line}`)
      }
    })

    this.process.on('exit', (code, signal) => {
      this.log(`ffmpeg exited: code=${code} signal=${signal}`)
      this.process = null
    })

    this.log('ffmpeg encoder started')
  }

  stop(): void {
    if (this.process) {
      this.process.kill('SIGTERM')
      this.process = null
    }
    this.buf = Buffer.alloc(0)
    this.onFrame = null
  }

  get pid(): number | undefined {
    return this.process?.pid
  }

  /**
   * Scan for SOI (0xFFD8) / EOI (0xFFD9) boundaries in the byte stream
   * and emit complete JPEG frames.
   */
  private feed(chunk: Buffer): void {
    this.buf = Buffer.concat([this.buf, chunk])

    while (true) {
      // Find start of JPEG
      const soiIdx = this.findMarker(this.buf, JPEG_SOI, 0)
      if (soiIdx < 0) {
        // No SOI found — discard everything
        this.buf = Buffer.alloc(0)
        return
      }

      // Discard anything before SOI
      if (soiIdx > 0) {
        this.buf = this.buf.subarray(soiIdx)
      }

      // Find end of JPEG (search from byte 2 to avoid matching the SOI itself)
      const eoiIdx = this.findMarker(this.buf, JPEG_EOI, 2)
      if (eoiIdx < 0) {
        // Incomplete frame — wait for more data
        return
      }

      // Extract complete JPEG (SOI through EOI + 2 bytes for the marker)
      const frameEnd = eoiIdx + 2
      const frame = this.buf.subarray(0, frameEnd)
      this.buf = this.buf.subarray(frameEnd)

      if (this.onFrame) {
        this.onFrame(Buffer.from(frame))
      }
    }
  }

  private findMarker(buf: Buffer, marker: number, startOffset: number): number {
    const hi = (marker >> 8) & 0xff
    const lo = marker & 0xff
    for (let i = startOffset; i < buf.length - 1; i++) {
      if (buf[i] === hi && buf[i + 1] === lo) {
        return i
      }
    }
    return -1
  }
}
