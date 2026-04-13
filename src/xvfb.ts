import { ChildProcess, spawn } from 'child_process'
import { existsSync } from 'fs'

export class Xvfb {
  private process: ChildProcess | null = null
  private readonly display: string
  private readonly resolution: string
  private readonly log: (msg: string) => void

  constructor(display: string, resolution: string, log: (msg: string) => void) {
    this.display = display
    this.resolution = resolution
    this.log = log
  }

  async start(): Promise<void> {
    const lockFile = `/tmp/.X${this.display.replace(':', '')}-lock`

    if (existsSync(lockFile)) {
      this.log(`Xvfb lock file ${lockFile} already exists, display may be in use`)
    }

    this.process = spawn('Xvfb', [
      this.display,
      '-screen', '0', this.resolution,
      '-ac',
      '-nolisten', 'tcp',
    ], {
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    this.process.stderr?.on('data', (data: Buffer) => {
      this.log(`Xvfb: ${data.toString().trim()}`)
    })

    this.process.on('exit', (code, signal) => {
      this.log(`Xvfb exited: code=${code} signal=${signal}`)
      this.process = null
    })

    await this.waitForDisplay(lockFile, 5000)
    this.log(`Xvfb started on ${this.display}`)
  }

  stop(): void {
    if (this.process) {
      this.process.kill('SIGTERM')
      this.process = null
    }
  }

  get pid(): number | undefined {
    return this.process?.pid
  }

  private waitForDisplay(lockFile: string, timeoutMs: number): Promise<void> {
    return new Promise((resolve, reject) => {
      const start = Date.now()
      const check = () => {
        if (existsSync(lockFile)) {
          resolve()
        } else if (Date.now() - start > timeoutMs) {
          reject(new Error(`Xvfb did not create ${lockFile} within ${timeoutMs}ms`))
        } else {
          setTimeout(check, 100)
        }
      }
      check()
    })
  }
}
