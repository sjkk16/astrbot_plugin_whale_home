// Test-only isolated renderer harness. Mock resources are never copied into a release.
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(path.join(root, 'frontend/package.json'))
const { build } = await import(pathToFileURL(require.resolve('vite')).href)
const { default: vue } = await import(pathToFileURL(require.resolve('@vitejs/plugin-vue')).href)
export async function buildMotionHarness(manifest) {
  const entry = path.join(root, 'frontend/__motion_harness.ts').replaceAll('\\', '/')
  const source = "import { createApp, h, reactive } from 'vue'; import CharacterRenderer from './src/components/CharacterRenderer.vue'; const state=reactive({source:'./art/scene-portrait.webp',styleId:'portrait',eventId:'one',custom:false,active:true}); window.__update=(values)=>Object.assign(state,values); window.__statuses=[]; const app=createApp({render:()=>h(CharacterRenderer,{...state,onStatus:value=>window.__statuses.push(value)})}); app.mount('#app'); window.__unmount=()=>app.unmount();"
  const result = await build({
    root: path.join(root, 'frontend'), configFile: false, publicDir: false, logLevel: 'error', define: { 'process.env.NODE_ENV': '"production"', __VUE_OPTIONS_API__: 'true', __VUE_PROD_DEVTOOLS__: 'false', __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: 'false' },
    plugins: [{ name: 'isolated-motion-fixture', enforce: 'pre',
      resolveId(id) { if (id.replaceAll('\\', '/').endsWith('/__motion_harness.ts')) return entry },
      load(id) {
        if (id.endsWith('/__motion_harness.ts') || id.endsWith('\\__motion_harness.ts')) return source
        if (/character-motion[\\/]manifest\.json$/.test(id)) return JSON.stringify(manifest)
      },
    }, vue()],
    build: { write: false, minify: false, target: 'es2022', lib: { entry, formats: ['es'], fileName: 'harness' } },
  })
  const resultList = Array.isArray(result) ? result : [result]
  return resultList.flatMap(r => r.output).find(o => o.type === 'chunk' && o.isEntry).code
}
