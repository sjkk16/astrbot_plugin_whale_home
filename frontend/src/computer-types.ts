export interface ComputerSite { domain: string; account: string; authenticated_read: boolean; like: boolean; favorite: boolean }
export interface ComputerPreferences {
  enabled: boolean; provider_id: string; vision_consent: boolean; autonomous_enabled: boolean
  mode: 'interest' | 'focused' | 'extended'; interests: string; topics: string; domains: string[]
  start_hour: number; end_hour: number; interval_minutes: number; daily_runs: number; extended_daily_runs: number
  minutes: number; steps: number; extended_minutes: number; extended_steps: number; daily_calls: number
  search_engine: 'bing' | 'duckduckgo'; sites: ComputerSite[]
}
export interface ReadingSource { url: string; title: string; at: string; private: boolean }
export interface ComputerTask {
  phase?: string; version?: number; error?: {code:string; retryable:boolean} | null
  id: string; topic: string; status: string; notice: string; trigger: string; steps: number; elapsed: number
  max_steps: number; max_seconds: number; summary: string; sources: ReadingSource[]; interest: string; takeover: boolean
  pending: null | { token: string; domain: string; account: string; target: string; content: string; url: string; action: { action: string; intent: string; text: string } }
}
export interface ComputerDownload { persistence_error?:string; id: string|null; version:number; status:string; message:string; progress:number|null; lines:string[] }
export interface ComputerState {
  download?:ComputerDownload
  version: number; preferences_version: number; preferences: ComputerPreferences; task: ComputerTask | null
  environment: ComputerEnvironment; usage: { calls: number; runs: number }; next_check: string | null
}
export interface ComputerEnvironment { browser_source?:"downloaded"; download_available?:boolean; browser_directory?:string; launch_mode?:string; revision?:number; checked_at?:string; ready:boolean; reason:string; code?:string; stage?:string; python_executable?:string; python_version?:string; playwright_version?:string|null; chromium_path?:string|null; commands?:string[]; detail?:string }
export interface BrowserFrame { frame_id:string; session_id:string; captured_at:string; viewport:{x:number;y:number;width:number;height:number}; image: string; url: string; title: string; tab: string; tabs: { id: string; url: string }[]; width: number; height: number; page_version: string; sensitive: boolean; private: boolean }
export interface ReadingMemory { id: number; text: string; sources: ReadingSource[] }
