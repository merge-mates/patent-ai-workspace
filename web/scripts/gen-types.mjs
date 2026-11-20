// 결과 스키마(Pydantic) → JSON Schema → TypeScript 타입.
// 서버 응답 타입을 손으로 다시 쓰지 않으려고 뽑는다. 결과는 src/types/generated/ (손으로 고치지 않음).
// 실행: npm run gen:types  (루트에서 uv가 돌아야 한다)
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..', '..')
const outDir = join(here, '..', 'src', 'types', 'generated')

// 파이썬 쪽에서 스키마 묶음을 받는다
const raw = execFileSync('uv', ['run', '--quiet', 'python', 'scripts/web_schemas.py'], {
  cwd: root,
  encoding: 'utf-8',
})
const schemas = JSON.parse(raw)

mkdirSync(outDir, { recursive: true })
const banner = '/* 이 파일은 npm run gen:types가 만든다 (scripts/web_schemas.py). 손으로 고치지 않는다. */'
for (const [name, schema] of Object.entries(schemas)) {
  const ts = await compile(schema, name, {
    bannerComment: banner,
    additionalProperties: false,
    style: { singleQuote: true, semi: false },
  })
  writeFileSync(join(outDir, `${name}.ts`), ts)
  console.log(`src/types/generated/${name}.ts`)
}
