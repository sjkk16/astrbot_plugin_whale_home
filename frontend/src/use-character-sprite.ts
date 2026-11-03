import { onBeforeUnmount, shallowRef, watch } from 'vue'
import { previewArtwork, spriteMetrics } from './character-art'

interface DecodedSprite { src: string; width: number; height: number; anchorX: number }
const staticSources = new Set(['./art/portrait.webp', './art/scene-portrait.webp', './art/scene-chibi-neutral.webp', './art/scene-chibi-eat.webp', ...Object.values(previewArtwork)])
const cache = new Map<string, Promise<DecodedSprite>>()

function decode(source: string): Promise<DecodedSprite> {
  const cached = cache.get(source)
  if (cached) return cached
  const image = new Image()
  image.decoding = 'async'
  image.src = source
  const promise = image.decode().then(() => {
    if (!image.naturalWidth || !image.naturalHeight) throw new Error('Empty sprite')
    return { src: source, ...spriteMetrics(source), width: image.naturalWidth, height: image.naturalHeight }
  })
  // Never retain user-uploaded data URLs in a module-lifetime cache.
  if (staticSources.has(source)) {
    cache.set(source, promise)
    void promise.catch(() => cache.delete(source))
  }
  return promise
}

export function preloadCharacterSprites() {
  return Promise.allSettled(Object.values(previewArtwork).map(source => decode(source)))
}

export function useCharacterSprite(source: () => string, fallback: () => string) {
  const image = shallowRef<DecodedSprite>({ src: fallback(), ...spriteMetrics(fallback()) })
  let epoch = 0
  watch([source, fallback], async ([desired, safe]) => {
    const version = ++epoch
    let next: DecodedSprite
    try { next = await decode(desired) }
    catch {
      try { next = await decode(safe) }
      catch { next = { src: safe, ...spriteMetrics(safe) } }
    }
    // Source, dimensions and anchor switch together; slow previous decodes cannot win.
    if (version === epoch) image.value = next
  }, { immediate: true })
  onBeforeUnmount(() => { epoch++ })
  return image
}
