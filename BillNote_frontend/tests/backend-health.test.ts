import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readBackendHealth } from '../src/components/BackendHealth/health.ts'

test('HTTP success does not hide missing or broken media tools', () => {
  for (const ffmpeg of ['missing', 'error']) {
    assert.equal(readBackendHealth({ code: 0, data: { backend: 'ok', ffmpeg, db: 'ok' } }), 'degraded')
  }
  assert.equal(readBackendHealth({ code: 0, data: { backend: 'ok', ffmpeg: 'ok', db: 'error' } }), 'degraded')
})

test('healthy and invalid responses are distinguished', () => {
  assert.equal(readBackendHealth({ code: 0, data: { backend: 'ok', ffmpeg: 'ok', db: 'ok' } }), 'ok')
  for (const body of [null, {}, { code: 500 }, { code: 0, data: {} }]) {
    assert.equal(readBackendHealth(body), 'unreachable')
  }
})
