import { onBeforeUnmount, watch } from 'vue'
import type { Bridge } from './types'

// One ephemeral id per mounted page; no persistent tracking or extra schedulers.
export function usePresence(getBridge: () => Bridge | undefined, enabled: () => boolean, clientId: string) {
  let started = false
  let stopped = false
  let active = true
  let sending = false
  let queued = false
  let timer: ReturnType<typeof setInterval> | undefined
  let debounce: ReturnType<typeof setTimeout> | undefined
  let lastSent = 0

  async function send(forceHidden = false) {
    const bridge = getBridge()
    if (!started || stopped || !bridge) return
    if (sending) { queued = true; return }
    sending = true
    const visible = !forceHidden && enabled() && document.visibilityState === 'visible'
    const wasActive = active
    active = false
    lastSent = performance.now()
    try {
      await bridge.apiPost('companion/presence', { client_id: clientId, visible, active: visible && wasActive })
    } catch { active ||= wasActive } // Heartbeat retries presence, never a model or action.
    finally {
      sending = false
      if (queued && !stopped) { queued = false; void send() }
    }
  }
  function activity() {
    active = true
    if (debounce) return
    debounce = setTimeout(() => { debounce = undefined; void send() }, Math.max(200, 1000 - (performance.now() - lastSent)))
  }
  function visibility() {
    active = document.visibilityState === 'visible'
    void send()
  }
  function pagehide() { void send(true) } // Abrupt closes additionally expire via server TTL.
  function start() {
    if (started || stopped) return
    started = true
    document.addEventListener('pointerdown', activity, { passive: true })
    document.addEventListener('keydown', activity)
    document.addEventListener('input', activity, { passive: true })
    document.addEventListener('scroll', activity, { passive: true, capture: true })
    document.addEventListener('visibilitychange', visibility)
    window.addEventListener('pagehide', pagehide)
    timer = setInterval(() => void send(), 15000)
    void send()
  }
  watch(enabled, () => { active = true; void send() })
  onBeforeUnmount(() => {
    void send(true)
    stopped = true
    clearInterval(timer); clearTimeout(debounce)
    document.removeEventListener('pointerdown', activity)
    document.removeEventListener('keydown', activity)
    document.removeEventListener('input', activity)
    document.removeEventListener('scroll', activity, true)
    document.removeEventListener('visibilitychange', visibility)
    window.removeEventListener('pagehide', pagehide)
  })
  return { start }
}
