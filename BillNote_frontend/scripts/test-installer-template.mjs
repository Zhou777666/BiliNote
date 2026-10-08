// Verify the vendored template remains compatible with the locked Tauri CLI.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

const root = fileURLToPath(new URL('../', import.meta.url))
const read = path => readFileSync(join(root, path), 'utf8').replace(/\r\n/g, '\n')
const config = JSON.parse(read('src-tauri/tauri.conf.json'))
const cli = JSON.parse(read('node_modules/@tauri-apps/cli/package.json'))
assert.equal(cli.version, '2.10.1', 'Update the NSIS template to match the new Tauri CLI before upgrading')
assert.equal(config.bundle.windows.nsis.template, 'windows/installer.nsi')
assert.equal(config.bundle.windows.nsis.installerHooks, undefined, 'Compression must be set before the Tauri includes')

const template = read('src-tauri/windows/installer.nsi')
const compressor = '  SetCompressor /FINAL "{{compression}}"'
assert.equal(template.split(compressor).length, 2, 'There must be exactly one compressor directive')
assert.ok(template.indexOf(compressor) < template.indexOf('!include'), 'Set compression before NSIS macros modify the header')

// Every other byte must match the upstream MIT template: preserve its upgrade,
// uninstall, WebView2 and shortcut behavior rather than rewriting the installer.
const upstream = template.split('\n').slice(2).join('\n')
  .replace(compressor, '  SetCompressor /SOLID "{{compression}}"')
assert.equal(createHash('sha256').update(upstream).digest('hex'),
  'fe22026f68bdb3292fab376756035496ce0a35e3d580e06ebaa6a28295916eb3',
  'Unexpected changes to the upstream NSIS template')
assert.ok(read('src-tauri/windows/TAURI-NOTICE.txt').includes('MIT License'))
console.log('NSIS template check passed: CLI 2.10.1, early per-file compression, upstream behavior preserved')
