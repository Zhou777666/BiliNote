// Compile only the small health regression tests for Node 20 (no TS loader needed).
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import ts from 'typescript'

const root = fileURLToPath(new URL('../', import.meta.url))
const output = join(root, '.cache', 'health-tests')
mkdirSync(output, { recursive: true })
const compile = source => ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText
writeFileSync(join(output, 'health.mjs'), compile(readFileSync(join(root, 'src/components/BackendHealth/health.ts'), 'utf8')))
const tests = readFileSync(join(root, 'tests/backend-health.test.ts'), 'utf8').replace('../src/components/BackendHealth/health.ts', './health.mjs')
const testPath = join(output, 'health.test.mjs')
writeFileSync(testPath, compile(tests))
const result = spawnSync(process.execPath, ['--test', testPath], { stdio: 'inherit' })
if (result.error) throw result.error
process.exit(result.status ?? 1)
