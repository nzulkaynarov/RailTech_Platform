/** Вход по коду из письма (B-MAIL-1): хелперы экрана «Мы отправили письмо». */

/** Через сколько секунд после письма можно попросить ещё одно (сервер держит своё: 5 писем в час на адрес). */
export const RESEND_AFTER_SECONDS = 60;

/** Только цифры и не больше шести: вставка «123 456» или «Код: 123456» даёт «123456». */
export function codeDigits(value: string): string {
  return value.replace(/\D/g, '').slice(0, 6);
}

/** Сколько целых секунд ещё ждать до «Отправить ещё раз»; 0 — можно. */
export function secondsLeft(sentAt: number, now: number): number {
  return Math.max(0, Math.ceil((sentAt + RESEND_AFTER_SECONDS * 1000 - now) / 1000));
}
