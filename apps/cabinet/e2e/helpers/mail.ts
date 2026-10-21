import { execFileSync } from 'node:child_process';
import { standRoot } from './env';

/**
 * Почта стенда — консоль ERP: письма (приглашения, ссылки входа, коды КП) лежат в логах `erp-backend` / `erp-worker`.
 * Токены и коды читаются здесь в переменную процесса и уходят только в браузер: не печатаются, не пишутся в файлы.
 */
/** Логи одного контейнера: письма разных контейнеров нельзя читать одним потоком — compose перемешивает их строки по времени. */
function serviceChunks(service: string, since: string): string[] {
  const out = execFileSync(
    'docker',
    ['compose', '-f', 'infra/compose/base.yml', '-f', 'infra/compose/dev.yml', '--env-file', '.env', 'logs', '--no-log-prefix', '--since', since, service],
    { cwd: standRoot(), maxBuffer: 512 * 1024 * 1024 },
  );
  // quoted-printable: мягкие переносы и =XX (письма на 7 бит). Нам нужны только ASCII-фрагменты — токен, 6 цифр, адрес.
  const decoded = out
    .toString('latin1')
    .replace(/=\r?\n/g, '')
    .replace(/=([0-9A-F]{2})/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)));
  // Письма идут подряд: режем по заголовку письма (строка Subject: — за ней From, To и тело) и берём дописанные —
  // те, после которых есть разделитель из дефисов или следующее письмо.
  const parts = decoded.split(/^(?=Subject: )/m);
  return parts.filter((chunk, index) => index > 0 && (index < parts.length - 1 || /-{70,}$/m.test(chunk)));
}

/** Письма обоих контейнеров от старых к новым (по заголовку Date; при равенстве — порядок в логе). */
function mailChunks(since: string): string[] {
  const dated = ['erp-backend', 'erp-worker'].flatMap((service) => serviceChunks(service, since)).map((chunk, index) => ({ chunk, index, at: Date.parse(/^Date: (.*)$/m.exec(chunk)?.[1] ?? '') || 0 }));
  return dated.sort((a, b) => a.at - b.at || a.index - b.index).map((item) => item.chunk);
}

function messagesTo(email: string, since: string): string[] {
  const needle = new RegExp(`^To: (?:.*[<, ])?${email.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:[>, ]|$)`, 'm');
  return mailChunks(since).filter((chunk) => needle.test(chunk));
}

/** Токены всех ссылок входа (`/auth/magic#token=…`) в письмах на адрес, от старых к новым. */
export function magicTokens(email: string, since = '3h'): string[] {
  return messagesTo(email, since).flatMap((chunk) => {
    // в одном письме ссылка входа повторяется (кнопка и текст) и всегда одна и та же; иначе кусок лога склеил чужие письма — не берём
    const tokens = new Set([...chunk.matchAll(/\/auth\/magic#token=([A-Za-z0-9_.-]+)/g)].map((m) => m[1]));
    return tokens.size === 1 ? [...tokens] : [];
  });
}

/** Токен последней ссылки входа в письмах на адрес; `null`, если письма нет. */
export function latestMagicToken(email: string, since = '3h'): string | null {
  return magicTokens(email, since).at(-1) ?? null;
}

/** Ждёт ссылку, которой не было среди `known`, и возвращает её (письма уходят из очереди — не мгновенно). */
export async function waitNewMagicToken(email: string, known: string[], timeoutMs = 45_000): Promise<string> {
  const until = Date.now() + timeoutMs;
  for (;;) {
    const fresh = magicTokens(email).filter((token) => !known.includes(token)).at(-1);
    if (fresh) return fresh;
    if (Date.now() > until) throw new Error(`письмо со ссылкой входа для ${email} не пришло за ${timeoutMs / 1000} с`);
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

/** Последний код принятия КП (6 цифр) в письмах на адрес. */
export function latestQuoteCode(email: string, since = '30m'): string | null {
  const codes = messagesTo(email, since).flatMap((chunk) => {
    const found = new Set([...chunk.matchAll(/font-size:32px[^>]*>(\d{6})</g)].map((m) => m[1]));
    return found.size === 1 ? [...found] : [];
  });
  return codes.at(-1) ?? null;
}

/** Сколько писем ушло на адрес (для проверки «приглашение коллеге ушло»). */
export function mailCount(email: string, since = '30m'): number {
  return messagesTo(email, since).length;
}

/** Строки журнала контейнера ERP с подстрокой (для проверок «в логе нет ошибки»); письма сюда не попадают — токенов в результате нет. */
export function logLines(service: string, needle: string, since = '30m'): string[] {
  const out = execFileSync(
    'docker',
    ['compose', '-f', 'infra/compose/base.yml', '-f', 'infra/compose/dev.yml', '--env-file', '.env', 'logs', '--no-log-prefix', '--since', since, service],
    { cwd: standRoot(), maxBuffer: 512 * 1024 * 1024 },
  );
  return out.toString('utf8').split('\n').filter((line) => line.includes(needle)).map((line) => line.slice(0, 200));
}
