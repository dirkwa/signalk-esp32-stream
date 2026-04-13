import { ChildProcess, spawn, execSync } from 'child_process'

export class Chromium {
  private process: ChildProcess | null = null
  private readonly display: string
  private readonly url: string
  private readonly bin: string
  private readonly log: (msg: string) => void

  constructor(
    display: string,
    url: string,
    bin: string,
    log: (msg: string) => void,
  ) {
    this.display = display
    this.url = url
    this.bin = bin
    this.log = log
  }

  async start(): Promise<void> {
    const env = { ...process.env, DISPLAY: this.display }

    this.process = spawn(this.bin, [
      '--no-sandbox',
      '--disable-gpu',
      '--disable-software-rasterizer',
      '--disable-dev-shm-usage',
      '--kiosk',
      '--noerrdialogs',
      '--disable-infobars',
      '--disable-session-crashed-bubble',
      '--disable-features=TranslateUI',
      '--window-size=1024,600',
      '--window-position=0,0',
      this.url,
    ], {
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    this.process.stderr?.on('data', (data: Buffer) => {
      const line = data.toString().trim()
      if (line && !line.includes('DevTools listening')) {
        this.log(`Chromium: ${line}`)
      }
    })

    this.process.on('exit', (code, signal) => {
      this.log(`Chromium exited: code=${code} signal=${signal}`)
      this.process = null
    })

    await this.waitForWindow(env, 15000)
    this.log('Chromium ready')
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

  private waitForWindow(
    env: NodeJS.ProcessEnv,
    timeoutMs: number,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const start = Date.now()
      const check = () => {
        try {
          execSync('xdotool getactivewindow', { env, timeout: 2000 })
          resolve()
        } catch {
          if (Date.now() - start > timeoutMs) {
            reject(new Error('Chromium did not open a window within timeout'))
          } else {
            setTimeout(check, 500)
          }
        }
      }
      // Give Chromium a moment to initialize before polling
      setTimeout(check, 1000)
    })
  }
}
