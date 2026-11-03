import { motionManifest, safeMotionUrl } from './character-motion'
import type { AnimatedArt } from './character-motion'

/** A private URL gives each event/renderer its own animation timeline. A shared
 * image URL (even on a newly keyed <img>) can reuse a completed cached animation. */
export async function loadAnimatedWebp(art: AnimatedArt, signal: AbortSignal) {
  const expected = motionManifest.files[art.path]
  if (!expected || expected !== art.sha256) throw new Error('Undeclared WebP')
  signal.throwIfAborted()
  const response = await fetch(safeMotionUrl(art.path), { signal, credentials: 'same-origin' })
  if (!response.ok) throw new Error('WebP unavailable')
  const bytes = await response.arrayBuffer()
  if (bytes.byteLength > 64 * 1024 * 1024) throw new Error('Oversized WebP')
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('')
  if (digest !== expected) throw new Error('WebP digest mismatch')
  signal.throwIfAborted()
  const blob = new Blob([bytes], { type: 'image/webp' })
  const probeUrl = URL.createObjectURL(blob)
  const image = new Image()
  let rejectAbort: (reason: unknown) => void = () => {}
  const aborted = new Promise<never>((_, reject) => { rejectAbort = reject })
  const cancel = () => { image.src = ''; rejectAbort(signal.reason) }
  signal.addEventListener('abort', cancel, { once: true })
  try {
    image.src = probeUrl
    await Promise.race([image.decode(), aborted])
    signal.throwIfAborted()
    if (image.naturalWidth !== art.width || image.naturalHeight !== art.height) throw new Error('WebP geometry mismatch')
    // Do not reuse the probe's clock; playback starts only when this URL is shown.
    const url = URL.createObjectURL(blob)
    let disposed = false
    return { url, dispose() { if (!disposed) { disposed = true; URL.revokeObjectURL(url) } } }
  } finally {
    signal.removeEventListener('abort', cancel)
    image.src = ''
    URL.revokeObjectURL(probeUrl)
  }
}
