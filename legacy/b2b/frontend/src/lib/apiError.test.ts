import { describe, expect, it } from 'vitest';

import { extractApiErrorCode, isTransportCode, translateApiError } from './apiError';
import i18n from '@/i18n';

/**
 * Ошибка, показанная человеку, — это сообщение, а не внутренности HTTP-клиента.
 *
 * Прогон глазами 25-08 (на живой прод-сборке): при недоступном списке компаний оператор видел
 * красный тост «ERR_NETWORK», при отвергнутой загрузке файла — «ERR_BAD_REQUEST». Причина одна:
 * `extractCode` берёт `err.code` axios, тот подходит под UPPER_SNAKE, перевода для него нет —
 * и наружу уходит внутренний код клиента, вытесняя единственное полезное сообщение.
 *
 * Эталон Salesforce SF-BLOCKER-NAMED: отказ называет причину, понятную тому, кто его читает.
 */

function axiosError(over: Record<string, unknown>) {
  return { isAxiosError: true, ...over };
}

describe('перевод ошибки API', () => {
  it('код бэкенда переводится', () => {
    expect(translateApiError(axiosError({ response: { data: { detail: 'FILE_TOO_LARGE' } } }))).toBe(
      i18n.t('apiErrors.FILE_TOO_LARGE'),
    );
  });

  it('обрыв связи говорит человеческим текстом, а не «ERR_NETWORK»', () => {
    const message = translateApiError(axiosError({ code: 'ERR_NETWORK', message: 'Network Error' }));

    expect(message).not.toContain('ERR_');
    expect(message).toBe(i18n.t('apiErrors.ERR_NETWORK'));
  });

  it('«ERR_BAD_REQUEST» без кода в ответе даёт общий текст, а не сам себя', () => {
    // Ровно то, что видел оператор при подменённом .pdf: сервер объяснил причину, но
    // строкой-списком, разобрать её витрина не смогла и напечатала код своего клиента.
    const message = translateApiError(axiosError({ code: 'ERR_BAD_REQUEST', response: { data: {} } }));

    expect(message).toBe(i18n.t('apiErrors.UNKNOWN'));
    expect(message).not.toContain('ERR_BAD_REQUEST');
  });

  it('код бэкенда ПОБЕЖДАЕТ транспортный: у ответа с кодом печатается он', () => {
    const message = translateApiError(
      axiosError({ code: 'ERR_BAD_REQUEST', response: { data: { detail: 'FILE_CONTENT_MISMATCH' } } }),
    );

    expect(message).toBe(i18n.t('apiErrors.FILE_CONTENT_MISMATCH'));
  });

  it('незнакомый код БЭКЕНДА печатается как есть — это подсказка, а не мусор', () => {
    expect(translateApiError(axiosError({ response: { data: { detail: 'SOME_NEW_SERVER_CODE' } } }))).toBe(
      'SOME_NEW_SERVER_CODE',
    );
  });

  it('машинный суффикс отбрасывается, голова переводится', () => {
    const message = translateApiError(axiosError({ response: { data: { detail: 'FILE_TOO_LARGE:25mb' } } }));

    expect(message).toBe(i18n.t('apiErrors.FILE_TOO_LARGE'));
  });

  it('транспортные коды перечислены явно, а не угадываются по префиксу', () => {
    // `ERR_`-префикс не признак: у бэкенда есть свои коды на `ERR`-подобные слова, и правило
    // «всё, что начинается на ERR_» однажды съело бы настоящий код.
    expect(isTransportCode('ERR_NETWORK')).toBe(true);
    expect(isTransportCode('ECONNABORTED')).toBe(true);
    expect(isTransportCode('FILE_CONTENT_MISMATCH')).toBe(false);
  });

  it('код по-прежнему извлекается для ветвления вызывающей стороны', () => {
    expect(
      extractApiErrorCode(axiosError({ response: { data: { detail: 'BELOW_FLOOR_JUSTIFICATION_REQUIRED' } } })),
    ).toBe('BELOW_FLOOR_JUSTIFICATION_REQUIRED');
  });
});
