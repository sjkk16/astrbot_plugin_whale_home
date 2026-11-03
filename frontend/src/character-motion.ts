import { onBeforeUnmount, readonly, ref } from 'vue'
import data from '../preview-assets/art/character-motion/manifest.json'
import type { ArtworkFrame } from './character-art'

export type RenderMode = 'webp' | 'static'
export type CharacterStyle = 'portrait' | 'chibi'
export type MotionFrame = ArtworkFrame | 'neutral'
export interface StaticArt { path: string; width: number; height: number; foot_anchor: number[]; sha256: string }
export interface AnimatedArt extends StaticArt {
  reviewed: boolean; fps: number; frame_count: number; duration_ms: number; 
  source?: { kind: 'local-raster'; static_sha256: string; recipe: string; recipe_sha256: string }
}
export interface MotionEntry {
  static: StaticArt; webp: AnimatedArt | null
  loop: boolean; duration_seconds: number
}
export interface MotionCharacter {
  frames: Partial<Record<MotionFrame, MotionEntry>>
}
export interface MotionManifest {
  schema_version: number; status: string
  files: Record<string, string>; characters: Record<CharacterStyle, MotionCharacter>
}
export const motionManifest = data as MotionManifest
export const modeLabels: Record<RenderMode, string> = { webp: '透明动图', static: '静态' }
export const MOTION_STORAGE_KEY = 'whale-home:character-renderer:v1'
const persistent = ref(true)
const validMode = (value: unknown): value is RenderMode => value === 'webp' || value === 'static'
function storedMode(): RenderMode {
  try { const value = localStorage.getItem(MOTION_STORAGE_KEY); if (value === 'live2d') localStorage.setItem(MOTION_STORAGE_KEY, 'webp'); return validMode(value) ? value : 'webp' }
  catch { persistent.value = false; return 'webp' }
}
const selectedMode = ref<RenderMode>(storedMode())
export function useCharacterMotionPreference() {
  function setMode(value: string) {
    if (!validMode(value)) return
    selectedMode.value = value
    try { localStorage.setItem(MOTION_STORAGE_KEY, value); persistent.value = true } catch { persistent.value = false }
  }
  const sync = (event: StorageEvent) => { if (event.key === MOTION_STORAGE_KEY || event.key === null) selectedMode.value = storedMode() }
  window.addEventListener('storage', sync)
  onBeforeUnmount(() => window.removeEventListener('storage', sync))
  return { mode: readonly(selectedMode), setMode, persistent: readonly(persistent) }
}
export function safeMotionUrl(source: string): string {
  if (!/^\.\/art\/character-motion\/[A-Za-z0-9_./-]+$/.test(source) || source.split('/').some(p => p === '..' || p === '')) throw new Error('Unsafe character resource')
  const url = new URL(source, document.baseURI)
  if (url.origin !== location.origin) throw new Error('Non-local character resource')
  return url.href
}
export function entryForSource(style: CharacterStyle, source: string): [MotionFrame, MotionEntry] | null {
  return Object.entries(motionManifest.characters[style].frames).find(([name, entry]) =>
    entry?.static.path === source || (style === 'portrait' && name === 'neutral' && source === './art/portrait.webp')) as [MotionFrame, MotionEntry] | undefined || null
}
export interface RendererStatus { mode: RenderMode; reason: string; loading: boolean }
export function chooseRenderer(style: CharacterStyle, entry: MotionEntry | undefined, requested: RenderMode, reduced: boolean, custom: boolean): RendererStatus {
  if (custom) return { mode: 'static', reason: '自定义立绘保持原图', loading: false }
  if (reduced) return { mode: 'static', reason: '已遵循系统减少动态效果', loading: false }
  if (requested === 'static') return { mode: 'static', reason: '', loading: false }
  if (entry?.webp?.reviewed) return { mode: 'webp', reason: '', loading: false }
  return { mode: 'static', reason: '此动作尚无审核动图，当前使用静态原图', loading: false }
}
