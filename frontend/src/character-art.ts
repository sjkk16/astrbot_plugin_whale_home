import manifest from '../preview-assets/art/interaction-v030/manifest.json'
import type { CharacterPose, Companion, Emotion, Home } from './types'

export type ArtworkFrame = Exclude<Emotion | CharacterPose, 'neutral'>
export const artworkLabels: Record<ArtworkFrame, string> = {
  happy: '俏皮笑', thinking: '思考', sleepy: '困倦', shy: '害羞', sad: '难过',
  pet: '摸头', accept: '收礼', eat: '白饭进食', drink: '饮茶', read: '阅读', play: '掌机游戏', rest: '站立休息',
}
interface ArtworkEntry { path: string; width: number; height: number; foot_anchor?: number[] }
const entries: Partial<Record<ArtworkFrame, ArtworkEntry>> = manifest.variants

// Only reviewed files in the build manifest are requested; a pending asset is never probed.
export const previewArtwork = Object.fromEntries(Object.entries(entries).map(([name, entry]) => [name, entry.path])) as Partial<Record<ArtworkFrame, string>>
export const artworkProgress = {
  count: Object.keys(previewArtwork).length,
  total: Object.keys(artworkLabels).length,
  pending: manifest.pending_illustrations.map(name => artworkLabels[name as ArtworkFrame]),
}

export function currentPresentation(companion: Companion | undefined, now: number) {
  const current = companion?.presentation
  return current && (now < Date.parse(current.speech_until) || companion?.reply_interruptible) ? current : null
}

export function characterFrame(home: Home, companion: Companion | undefined, now: number, moving = false): ArtworkFrame | 'neutral' {
  const current = currentPresentation(companion, now)
  if (!current || moving || home.settings.character_style === 'chibi' || home.settings.portrait_asset) return 'neutral'
  if (now < Date.parse(current.pose_until) && current.pose !== 'neutral') {
    if (previewArtwork[current.pose]) return current.pose
    // Honest partial-preview fallback; never claim it is the missing action illustration.
    const fallback = current.pose === 'rest' ? 'sleepy' : current.pose === 'read' ? 'thinking' : 'happy'
    if (previewArtwork[fallback]) return fallback
  }
  if (current.model_status === 'pending' && previewArtwork.thinking) return 'thinking'
  return current.emotion !== 'neutral' && previewArtwork[current.emotion] ? current.emotion : 'neutral'
}

export function missingPoseLabel(home: Home, companion: Companion | undefined, now: number) {
  const current = currentPresentation(companion, now)
  if (home.settings.character_style !== 'portrait' || home.settings.portrait_asset || !current
      || now >= Date.parse(current.pose_until) || current.pose === 'neutral' || previewArtwork[current.pose]) return ''
  return `${artworkLabels[current.pose]}专用图待补，当前仅用表情反馈。`
}

export function frameForSource(source: string): ArtworkFrame | 'neutral' {
  return (Object.keys(previewArtwork) as ArtworkFrame[]).find(frame => previewArtwork[frame] === source) || 'neutral'
}

export function spriteMetrics(source: string) {
  const entry = Object.values(entries).find(entry => entry?.path === source)
  if (entry) return { width: entry.width, height: entry.height, anchorX: entry.foot_anchor?.[0] ?? .5 }
  if (source === './art/scene-portrait.webp') {
    const reference = (manifest as { reference?: { width: number; height: number; foot_anchor: number[] } }).reference
    return { width: reference?.width ?? 500, height: reference?.height ?? 991, anchorX: reference?.foot_anchor[0] ?? .5 }
  }
  return { width: source.includes('chibi') ? 362 : 500, height: source.includes('chibi') ? 482 : 991, anchorX: .5 }
}

export function portraitSource(home: Home, companion: Companion | undefined, now: number, images: Record<string, string>) {
  if (home.settings.portrait_asset) return images[home.settings.portrait_asset] || './art/portrait.webp'
  const frame = characterFrame(home, companion, now)
  return frame === 'neutral' ? './art/portrait.webp' : previewArtwork[frame] || './art/portrait.webp'
}
