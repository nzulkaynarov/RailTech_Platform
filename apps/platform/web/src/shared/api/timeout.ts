/**
 * Предел ожидания ответа BFF для экранов, где зависание — тупик (первый запуск, W13C-F1). BFF сам обрывает бэкенды за
 * несколько секунд, так что этот предел срабатывает только при потерянной связи с самим BFF: экран получает
 * `ApiError` с кодом `REQUEST_TIMEOUT` и показывает «Повторить», а не вечную загрузку.
 */
export const SETUP_TIMEOUT_MS = 20_000;

/** Сигнал, который срабатывает по отмене запроса react-query или по истечении `ms`, смотря что раньше. */
export function withTimeout(
  signal: AbortSignal | undefined,
  ms: number = SETUP_TIMEOUT_MS,
): AbortSignal {
  const timeout = AbortSignal.timeout(ms);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}
