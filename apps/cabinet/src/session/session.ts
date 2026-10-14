import { authTelegram, getMe, isPortalApiError, type Me } from '@/api/portal';
import { applyContactLanguage } from '@/i18n';
import { getInitData, isMiniApp } from '@/telegram/webapp';

/**
 * Загрузка сессии портала — ключ React Query `['me']`.
 *
 * - Mini App: при старте всегда `POST /auth/telegram {init_data}` (без страницы входа) — сессия
 *   гарантированно принадлежит тому, кто открыл бота. Дальше — `GET /me`; на 401 (сессия истекла)
 *   — ещё одна попытка `POST /auth/telegram`; если и она 401 (`initData` старше 5 минут) — экран
 *   «Откройте кабинет из бота ещё раз».
 * - Веб: `GET /me`; 401 → `null` (нет сессии → страница входа).
 */
export const ME_QUERY_KEY = ['me'] as const;

let telegramAuthDone = false;

/** Для тестов: следующий запуск снова начнётся с `POST /auth/telegram`. */
export function resetSessionBootstrap(): void {
  telegramAuthDone = false;
}

export async function loadSession(): Promise<Me | null> {
  if (isMiniApp()) {
    if (!telegramAuthDone) {
      const me = await authTelegram(getInitData());
      telegramAuthDone = true;
      return afterSignIn(me);
    }
    try {
      return await getMe();
    } catch (error) {
      if (isPortalApiError(error, 401)) return afterSignIn(await authTelegram(getInitData()));
      throw error;
    }
  }
  try {
    return afterSignIn(await getMe());
  } catch (error) {
    if (isPortalApiError(error, 401)) return null;
    throw error;
  }
}

/** После любого входа: язык контакта, если человек не выбирал язык сам. */
export function afterSignIn(me: Me): Me {
  void applyContactLanguage(me.contact.language);
  return me;
}
