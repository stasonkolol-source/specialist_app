// orval: клиент API из backend/openapi.json (DEVELOPMENT_PLAN 0.20, ADR-0003).
// Генерируются типы, fetchers, хуки TanStack Query, Zod-схемы и MSW-моки; все вызовы идут
// через свой mutator (src/mutator.ts): база /api/v1, Bearer из памяти, RFC 9457 → ApiError.
import { defineConfig } from 'orval';
import type { OpenAPIObject } from 'orval';

/** Необязательный заголовок в схеме — `anyOf [string, null]` (FastAPI `Header(None)`). У заголовка
 *  нет «null на проводе»: не передан — не отправлен. Без null типы ложатся в HeadersInit. */
const headersWithoutNull = (spec: OpenAPIObject): OpenAPIObject => {
  for (const item of Object.values(spec.paths ?? {})) {
    for (const operation of Object.values(item ?? {})) {
      const parameters = (operation as { parameters?: unknown[] }).parameters ?? [];
      for (const parameter of parameters as { in?: string; schema?: Record<string, unknown> }[]) {
        const anyOf = parameter.schema?.anyOf as Record<string, unknown>[] | undefined;
        if (parameter.in !== 'header' || !anyOf) continue;
        const [only, ...rest] = anyOf.filter((variant) => variant.type !== 'null');
        if (only && rest.length === 0) {
          const schema = { ...parameter.schema, ...only };
          delete schema.anyOf;
          parameter.schema = schema;
        }
      }
    }
  }
  return spec;
};

const input = {
  target: '../../backend/openapi.json',
  override: { transformer: headersWithoutNull },
};

export default defineConfig({
  api: {
    input,
    output: {
      mode: 'tags-split',
      target: 'src/generated/endpoints',
      schemas: 'src/generated/model',
      client: 'react-query',
      httpClient: 'fetch',
      mock: { generators: [{ type: 'msw', delay: false }] },
      clean: true,
      headers: true,
      override: {
        mutator: { path: 'src/mutator.ts', name: 'apiFetch' },
        fetch: { includeHttpResponseReturnType: false },
        query: { signal: true },
      },
    },
    hooks: { afterAllFilesWrite: 'prettier --write' },
  },
  zod: {
    input,
    output: {
      mode: 'tags-split',
      target: 'src/generated/zod',
      client: 'zod',
      fileExtension: '.zod.ts',
      clean: true,
    },
    hooks: { afterAllFilesWrite: 'prettier --write' },
  },
});
