/**
 * «Свежий код» второго фактора (ДВ-4б): токен на 5 минут, который BFF и CRM проверяют на чувствительных действиях
 * (выдача роли, подтверждение новых банковских реквизитов). Хранится только в памяти вкладки; `http` добавляет его
 * заголовком `X-Step-Up-Token` к изменяющим запросам, пока токен свежий. Проверка — на сервере; здесь только удобство:
 * после ввода кода повторное действие в течение минут не спрашивает код снова.
 */

/** Запас до конца срока сервера (300 с), чтобы не отправить токен, который истечёт по дороге. */
const TTL_MS = 270_000;

let token: { value: string; until: number } | null = null;

export function rememberStepUp(value: string, now: number = Date.now()): void {
  token = { value, until: now + TTL_MS };
}

export function forgetStepUp(): void {
  token = null;
}

/** Токен, если он ещё свеж. */
export function freshStepUp(now: number = Date.now()): string | null {
  if (token && token.until > now) return token.value;
  token = null;
  return null;
}
