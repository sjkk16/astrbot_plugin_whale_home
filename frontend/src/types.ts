export interface Position { x: number; y: number }
export type Usage = 'eat' | 'drink' | 'read' | 'play' | 'rest' | 'decorate'
export type Panel = 'chat' | 'items' | 'diary' | 'settings' | 'activities' | 'computer' | 'more' | null
export type Location = 'desk' | 'window' | 'bedside'
export type SpotId = 'bookshelf' | 'desk' | 'window' | 'bed'
export interface SceneAnchor { x: number; y: number; height: number; light: string }
export interface SceneSpot {
  id: SpotId; name: string; label: string; action: 'read' | 'play' | 'move' | 'rest'
  location: Location; description: string; rect: [number, number, number, number]; marker: [number, number]
}
export interface Scene {
  id: string; title: string; background: string; width: number; height: number
  locations: Record<Location, SceneAnchor>; spots: SceneSpot[]
}
export interface Settings {
  provider_id: string
  autonomous_enabled: boolean
  interval_minutes: number
  daily_limit: number
  timezone: string
  character_name: string
  user_name: string
  persona: string
  chibi_asset: string | null
  portrait_asset: string | null
  room_asset: string | null
  character_style: 'portrait' | 'chibi'
}
export interface Definition {
  id: string
  name: string
  description: string
  category: 'food' | 'drink' | 'book' | 'toy' | 'furniture' | 'decoration'
  usage: Usage
  width: number
  height: number
  blocks_movement: boolean
  consumable: boolean
  builtin: boolean
  icon: string
  asset_id: string | null
}
export interface Instance {
  id: string
  definition_id: string
  quantity: number
  position: null
}
export interface Character {
  location: Location
  satiety: number
  energy: number
  mood: number
  bond: number
  activity: string
  emotion: string
  speech: string
  last_path: Location[]
  movement_id: string
  activity_target: string
}
export interface Home {
  schema_version: 2
  version: number
  world_version: number
  settings: Settings
  character: Character
  definitions: Definition[]
  instances: Instance[]
}
export interface Message {
  id: number; created_at: string; role: 'user' | 'assistant' | 'system'
  source: string; text: string
}
export interface HomeEvent {
  id: number; created_at: string; kind: string; text: string
  details: Record<string, unknown>
}
export interface Memory { id: number; created_at: string; source: string; text: string }
export interface Snapshot {
  computer?: import('./computer-types').ComputerState
  companion?: Companion
  skills?: SkillsState
  scene: Scene
  home: Home
  usage: { day: string; autonomy: number; chat: number }
  runtime: { busy: boolean; next_decision_at: string | null; last_error: string; server_time: string }
  messages: Message[]
  events: HomeEvent[]
  memories: Memory[]
}
export interface Provider { id: string; name: string }
export interface Bridge {
  ready(): Promise<{ demo?: boolean; isDark?: boolean; locale?: string }>
  apiGet<T>(endpoint: string, params?: Record<string, string | number>): Promise<T>
  apiPost<T>(endpoint: string, body: unknown): Promise<T>
  upload<T>(endpoint: string, file: File): Promise<T>
  download(endpoint: string, params?: Record<string, string>, filename?: string): Promise<unknown>
  subscribeSSE(
    endpoint: string,
    handlers: { onMessage?: (event: { parsed: { type: string } }) => void; onError?: () => void; onOpen?: () => void },
  ): Promise<string>
  unsubscribeSSE(id: string): Promise<void>
}
declare global {
  interface Window { AstrBotPluginView?: Bridge }
}



export type Emotion = 'neutral' | 'happy' | 'thinking' | 'sleepy' | 'shy' | 'sad'
export type CharacterPose = 'neutral' | 'pet' | 'accept' | 'eat' | 'drink' | 'read' | 'play' | 'rest'
export interface CompanionPreferences {
  interaction_model_enabled: boolean
  proactive_enabled: boolean
  idle_minutes: number
  interval_minutes: number
  daily_limit: number
}
export interface Presentation {
  id: string; pose: CharacterPose; emotion: Emotion; speech: string
  source: 'interaction' | 'chat' | 'autonomy' | 'proactive'
  model_status: 'local' | 'pending' | 'model' | 'error'
  created_at: string; pose_until: string; speech_until: string
}
export interface Companion {
  preferences: CompanionPreferences
  presentation: Presentation | null
  notice: string
  reply_interruptible: boolean
  awaiting_reply: boolean
  visible: boolean
  usage: { interaction: number; proactive: number }
  limits: { interaction_interval_seconds: number; interaction_daily_limit: number; presence_ttl_seconds: number }
  touch_available_at?: string | null
  persona_preset: string
}
export type DirectInteraction =
  | { kind: 'pet' }
  | { kind: 'scene'; spot_id: SpotId }
  | { kind: 'item'; instance_id: string; mode: 'use' | 'gift' }

export interface SkillPreferences {
  enabled: boolean
  access_mode: 'restricted' | 'full'
  allowed_tools: string[]
  allowed_skills: string[]
}
export interface Capability {
  name: string; kind: 'tool' | 'skill'; description: string; source: string
  available: boolean; reason: string
}
export interface SkillCall {
  id: number; run_id: string; name: string; kind: 'tool' | 'skill'; source: string
  trigger: string; status: 'running' | 'succeeded' | 'failed' | 'denied' | 'unknown'
  created_at: string; duration_ms: number | null; error_code: string
}
export interface SkillsState {
  preferences: SkillPreferences
  active: { run_id: string; trigger: string; name: string; stopping: boolean } | null
  calls: SkillCall[]
  output: string
}
