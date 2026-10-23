#!/usr/bin/env node
/**
 * Типы публичной формы CRM «Запрос» (`/api/v1/leads/web*`, M3-CRM-05 / M2-CAB-03) для Cabinet.
 *
 * Источник — OpenAPI CRM (`packages/contracts/openapi/crm.yaml`, `make -C apps/crm openapi`). Из всей
 * схемы CRM берутся только пути формы и схемы, на которые они ссылаются (транзитивно): остального
 * API CRM Cabinet не знает (CONVENTIONS.md §2.1). Результат — в stdout:
 *
 *   make gen-api-types     → src/api/crm-form.d.ts
 *   make api-types-check   — сверка с закоммиченным файлом.
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import openapiTS, { astToString } from 'openapi-typescript';
import { parse } from 'yaml';

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, '../../../packages/contracts/openapi/crm.yaml');
const PATH_PREFIX = '/api/v1/leads/web';
const SCHEMA_REF = '#/components/schemas/';

const spec = parse(readFileSync(source, 'utf8'));
const paths = Object.fromEntries(Object.entries(spec.paths).filter(([path]) => path.startsWith(PATH_PREFIX)));

/** Схемы, достижимые по `$ref` из путей формы. */
const schemas = {};
const queue = [paths];
while (queue.length > 0) {
  const node = queue.pop();
  if (Array.isArray(node)) {
    queue.push(...node);
  } else if (node && typeof node === 'object') {
    for (const [key, value] of Object.entries(node)) {
      if (key === '$ref' && typeof value === 'string' && value.startsWith(SCHEMA_REF)) {
        const name = value.slice(SCHEMA_REF.length);
        if (!(name in schemas)) {
          schemas[name] = spec.components.schemas[name];
          queue.push(schemas[name]);
        }
      } else {
        queue.push(value);
      }
    }
  }
}

const subset = {
  openapi: spec.openapi,
  info: { title: `${spec.info.title}: форма «Запрос» для Cabinet`, version: spec.info.version },
  paths,
  components: { schemas: Object.fromEntries(Object.entries(schemas).sort(([a], [b]) => a.localeCompare(b))) },
};

const ast = await openapiTS(subset);
process.stdout.write(
  '/**\n * Сгенерировано scripts/gen-crm-form-types.mjs из packages/contracts/openapi/crm.yaml — не править руками.\n */\n\n' +
    astToString(ast),
);
