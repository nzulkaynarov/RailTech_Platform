// Валидация events/asyncapi.yaml закреплённым @asyncapi/parser (package.json, pnpm-lock.yaml):
// AsyncAPI 3.0, разрешение $ref на файлы схем, правила spectral из парсера. Ошибка или предупреждение — код 1.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { Parser, fromFile } from '@asyncapi/parser';

const file = resolve(process.argv[2] ?? 'events/asyncapi.yaml');
const parser = new Parser();
const { document, diagnostics } = await fromFile(parser, file).parse({
  source: pathToFileURL(file).href,
});
// severity: 0 error, 1 warning, 2 info, 3 hint
const problems = diagnostics.filter((d) => d.severity <= 1);
for (const d of diagnostics) {
  const level = ['error', 'warning', 'info', 'hint'][d.severity] ?? d.severity;
  console.log(`${level} ${d.code} ${d.path.join('.')}: ${d.message}`);
}
if (!document || problems.length) {
  console.error(`asyncapi: ${problems.length} ошибок/предупреждений в ${file}`);
  process.exit(1);
}
const channels = document.channels().all().length;
const messages = document.messages().all().length;
console.log(`asyncapi: ${file} валиден (AsyncAPI ${document.version()}, каналов ${channels}, сообщений ${messages})`);
