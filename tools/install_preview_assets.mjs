import { installMotionAssets } from './character_motion.mjs'
// Install reviewed artwork into an explicitly selected build; never alter original/Q art.
import { createHash } from 'node:crypto'
import { copyFile, mkdir, readFile, readdir, realpath } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const args = process.argv.slice(2)
if (args.length > 1 || (args.length === 1 && !['--release', '--skills-preview'].includes(args[0]))) throw new Error('Expected --release, --skills-preview or no arguments')
const release = args[0] === '--release'
const root = await realpath(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'))
const source = path.join(root, 'frontend/preview-assets/art/interaction-v030')
const target = path.join(root, release ? 'views/home' : args[0] === '--skills-preview' ? 'artifacts/skills-preview/preview-site' : 'artifacts/interaction-v030/preview-site')
const site = await realpath(target)
if (site !== target) throw new Error('Unexpected artwork output target')
const destination = path.join(site, 'art/interaction-v030')
const manifest = JSON.parse(await readFile(path.join(source, 'manifest.json'), 'utf8'))
const files = Object.entries(manifest.variants)
const required = ['happy', 'thinking', 'sleepy', 'shy', 'sad', 'pet', 'accept', 'eat', 'drink', 'read', 'play', 'rest']
if (release && (files.length !== required.length || required.some(id => !manifest.variants[id]) || manifest.pending_illustrations.length)) throw new Error('Release requires all 12 reviewed illustrations')
const expectedFiles = ['manifest.json', ...files.map(([id]) => id + '.webp')].sort()
if (JSON.stringify((await readdir(source)).sort()) !== JSON.stringify(expectedFiles)) throw new Error('Unreviewed artwork in source directory')
for (const [id, record] of files) {
  if (!required.includes(id) || record.path !== './art/interaction-v030/' + id + '.webp') throw new Error('Unsafe manifest entry')
  const file = path.join(source, id + '.webp')
  if (await realpath(file) !== file) throw new Error('Linked artwork is not allowed')
  const data = await readFile(file)
  if (createHash('sha256').update(data).digest('hex') !== record.sha256) throw new Error('Artwork digest mismatch: ' + id)
}
await mkdir(destination, { recursive: true })
if (await realpath(destination) !== destination) throw new Error('Linked output is not allowed')
for (const name of expectedFiles) {
  const file = path.join(destination, name)
  try { if (await realpath(file) !== file) throw new Error('Linked output file is not allowed') }
  catch (error) { if (error.code !== 'ENOENT') throw error }
  await copyFile(path.join(source, name), file)
}
console.log('Installed ' + files.length + ' verified interaction variants into ' + (release ? 'release' : 'isolated preview') + ' build.')

await installMotionAssets(root, site)
