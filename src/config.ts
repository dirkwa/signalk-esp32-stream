export interface PluginConfig {
  kipUrl: string
  display: string
  resolution: string
  streamPort: number
  touchPort: number
  jpegQuality: number
  framerate: number
  chromiumBin: string
}

export const defaults: PluginConfig = {
  kipUrl: 'http://192.168.0.148:3000/@signalk/app-dock/',
  display: ':99',
  resolution: '1024x600x24',
  streamPort: 5004,
  touchPort: 5005,
  jpegQuality: 5,
  framerate: 15,
  chromiumBin: 'chromium-browser',
}

export const schema = {
  type: 'object' as const,
  properties: {
    kipUrl: {
      type: 'string',
      title: 'KIP URL',
      default: defaults.kipUrl,
    },
    display: {
      type: 'string',
      title: 'Virtual display number',
      default: defaults.display,
    },
    resolution: {
      type: 'string',
      title: 'Virtual display resolution (WxHxD)',
      default: defaults.resolution,
    },
    streamPort: {
      type: 'number',
      title: 'MJPEG stream TCP port',
      default: defaults.streamPort,
    },
    touchPort: {
      type: 'number',
      title: 'Touch event UDP port',
      default: defaults.touchPort,
    },
    jpegQuality: {
      type: 'number',
      title: 'JPEG quality (2-10, lower = better)',
      default: defaults.jpegQuality,
      minimum: 2,
      maximum: 10,
    },
    framerate: {
      type: 'number',
      title: 'Capture framerate (fps)',
      default: defaults.framerate,
      minimum: 1,
      maximum: 30,
    },
    chromiumBin: {
      type: 'string',
      title: 'Chromium binary path',
      default: defaults.chromiumBin,
    },
  },
}
