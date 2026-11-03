// Shared build-time validation. Python performs the additional pixel/timing audits.
import { createHash } from 'node:crypto'
import { readFile, readdir, realpath, copyFile, mkdir } from 'node:fs/promises'
import path from 'node:path'
export const prefix = './art/character-motion/'
export const relativeDirectory = 'frontend/preview-assets/art/character-motion'
export function assetRelative(url) {
  if (typeof url !== 'string' || !url.startsWith(prefix)) throw new Error('Non-local motion resource')
  const relative = url.slice(prefix.length)
  if (!/^[A-Za-z0-9_./-]+$/.test(relative) || relative.split('/').some(p => !p || p === '.' || p === '..')) throw new Error('Unsafe motion resource')
  return relative
}
export async function checked(base, relative) {
  const file = path.resolve(base, relative)
  if (!file.startsWith(path.resolve(base) + path.sep) || await realpath(file) !== file) throw new Error('Linked or escaped motion resource')
  return file
}
export async function validateMotionAssets(root) {
  const base = path.join(root, relativeDirectory)
  const manifestFile = await checked(base, 'manifest.json')
  const manifest = JSON.parse(await readFile(manifestFile, 'utf8'))
  if (manifest.schema_version !== 2 || 'sdk' in manifest) throw new Error('Unsupported motion manifest')
  if (JSON.stringify(Object.keys(manifest.characters).sort()) !== '["chibi","portrait"]') throw new Error('Invalid review state')
  const expected = ['manifest.json']
  for (const [url, hash] of Object.entries(manifest.files)) {
    const relative = assetRelative(url)
    const file = await checked(base, relative)
    if (!['.json', '.png', '.webp'].includes(path.extname(file))) throw new Error('Unreviewed motion extension')
    if (createHash('sha256').update(await readFile(file)).digest('hex') !== hash) throw new Error('Motion digest mismatch: ' + url)
    expected.push(relative)
  }
  async function list(dir, sub = '') {
    const files = []
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (entry.isSymbolicLink()) throw new Error('Linked motion resource')
      files.push(...(entry.isDirectory() ? await list(path.join(dir, entry.name), sub + entry.name + '/') : [sub + entry.name]))
    }
    return files
  }
  if (JSON.stringify((await list(base)).sort()) !== JSON.stringify(expected.sort())) throw new Error('Unreviewed motion files')
  let animations = 0
  for (const [style, character] of Object.entries(manifest.characters)) {
    if (JSON.stringify(Object.keys(character)) !== '["frames"]') throw new Error('Unknown character fields')
    const names = style === 'portrait' ? ['neutral', 'happy', 'thinking', 'sleepy', 'shy', 'sad', 'pet', 'accept', 'eat', 'drink', 'read', 'play', 'rest'] : ['neutral', 'eat']
    if (JSON.stringify(Object.keys(character.frames).sort()) !== JSON.stringify(names.sort())) throw new Error('Expected 15 presentations')
    for (const [name, frame] of Object.entries(character.frames)) {
      if (Object.keys(frame).sort().join(',') !== 'duration_seconds,loop,static,webp') throw new Error('Unknown frame fields')
      if (frame.loop !== !['pet', 'accept', 'eat', 'drink'].includes(name) || !(frame.duration_seconds > 0 && frame.duration_seconds <= 10)) throw new Error('Invalid motion timing')
      if (frame.webp) {
        const webp = frame.webp
        if (Object.keys(webp).sort().join(',') !== 'duration_ms,foot_anchor,fps,frame_count,height,path,reviewed,sha256,source,width') throw new Error('Unknown animation fields')
        if (typeof webp.reviewed !== 'boolean' || !Number.isInteger(webp.fps) || !Number.isInteger(webp.frame_count) || webp.frame_count < 2 || webp.frame_count > 600 || !(webp.duration_ms > 0 && webp.duration_ms <= 10000) || !manifest.files[webp.path] || manifest.files[webp.path] !== webp.sha256) throw new Error('Unreviewed or stale WebP')
        const raster = webp.source?.kind === 'local-raster'
        if (!raster) throw new Error('Unknown animation source')
        if (raster) {
          const source = webp.source
          if (webp.fps !== 20) throw new Error('Local raster animation must be 20 fps ')
          if (source.static_sha256 !== frame.static.sha256) throw new Error('Raster animation source differs from static fallback')
          if (typeof source.recipe !== 'string' || !source.recipe.endsWith('.json') || !manifest.files[source.recipe] || manifest.files[source.recipe] !== source.recipe_sha256) throw new Error('Undeclared raster recipe')
          const recipe = JSON.parse(await readFile(await checked(base, assetRelative(source.recipe)), 'utf8'))
          if (recipe.kind !== 'local-raster' || recipe.schema_version !== 1 || recipe.static_sha256 !== frame.static.sha256 || recipe.output_sha256 !== webp.sha256 || recipe.fps !== webp.fps || recipe.frame_count !== webp.frame_count || recipe.duration_ms !== webp.duration_ms || webp.frame_count * 1000 / webp.fps !== webp.duration_ms) throw new Error('Stale raster recipe')
        }
        if (webp.width !== frame.static.width || webp.height !== frame.static.height || JSON.stringify(webp.foot_anchor) !== JSON.stringify(frame.static.foot_anchor) || webp.duration_ms !== Math.round(frame.duration_seconds * 1000)) throw new Error('Animation geometry or frame metadata differs')
        if (webp.reviewed) animations++
      }
    }
  }
  if (manifest.status === 'complete' && animations !== 15) throw new Error('Manifest falsely claims completion')
  return { manifest, base, files: expected }
}
export async function installMotionAssets(root, site) {
  const { manifest, base, files } = await validateMotionAssets(root)
  const destination = path.join(site, 'art/character-motion')
  await mkdir(destination, { recursive: true })
  if (await realpath(destination) !== destination) throw new Error('Linked motion output')
  for (const relative of files) {
    const to = path.join(destination, relative)
    await mkdir(path.dirname(to), { recursive: true })
    if (await realpath(path.dirname(to)) !== path.dirname(to)) throw new Error('Linked output directory')
    try { if (await realpath(to) !== to) throw new Error('Linked motion output file') } catch (e) { if (e.code !== 'ENOENT') throw e }
    await copyFile(path.join(base, relative), to)
  }
  const animations = Object.values(manifest.characters).flatMap(c => Object.values(c.frames)).filter(f => f.webp?.reviewed).length
  console.log('Character animation: ' + animations + '/15 reviewed raster animations; other presentations use static artwork.')
}
