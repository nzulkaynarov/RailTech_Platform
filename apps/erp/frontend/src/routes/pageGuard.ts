/**
 * Единое решение о доступе к странице (контекст покупателя/продавца).
 *
 * Вынесено ЧИСТОЙ функцией, чтобы её можно было покрыть юнит-тестами и чтобы три
 * исторически раздельных guard-эффекта опирались на один источник правды. Наборы страниц
 * берутся из реестра (`config/pageRegistry`) — новая страница не может «потеряться» в одном
 * из них.
 *
 * `bootstrapped` — несущий вход для починки cold-load deep-link: пока `loadFromAuth`
 * не разрешил реальные capabilities (сигнал — `screen === 'main'`), стор держит
 * ПРЕД-авторизационные ДЕФОЛТЫ: activeStatus 'BUYER', пустые statusEntries. Применение
 * гейтов к ним на холодном deep-link (`#request-detail/3`, `#deal-quote/7`) ошибочно
 * провалило бы проверку контекста и отбросило страницу на #dashboard (затерев хэш через
 * replaceState). Поэтому пока `!bootstrapped` — РАЗРЕШАЕМ
 * (откладываем); эффект перезапустится, когда capabilities приедут, и применит гейты
 * ровно как раньше.
 *
 * Порога верификации компании больше нет (M1-ERP-02): проверки клиентов в ERP нет, действия
 * ограничивает право роли — его держит бэкенд, а меню прячет недоступное (`config/navigation`).
 */

import { BUYER_PAGES, SELLER_PAGES } from '@/config/pageRegistry';
import type { CompanyStatus, CompanyStatusEntry } from '@/store/userStore';

export type PageGuardDecision =
  | { action: 'allow' }
  | { action: 'adopt'; context: CompanyStatus }
  | { action: 'bounce'; reason: 'context' };

export interface PageGuardInput {
  pageType: string;
  activeStatus: CompanyStatus;
  statusEntries: CompanyStatusEntry[];
  bootstrapped: boolean;
}

/**
 * ADR-0005 Phase C — контекст, выводимый из страницы. Страница, УНИКАЛЬНАЯ для одной стороны,
 * подразумевает этот рабочий контекст; страницы из ОБОИХ наборов (дашборд, каталог, карточка
 * заявки, общие документы…) контекстно-нейтральны → оставляем текущий контекст пользователя.
 */
export function pageContextOf(pageType: string): CompanyStatus | null {
  const inBuyer = BUYER_PAGES.has(pageType);
  const inSeller = SELLER_PAGES.has(pageType);
  if (inBuyer && !inSeller) return 'BUYER';
  if (inSeller && !inBuyer) return 'SELLER';
  return null;
}

export function evaluatePageGuard(input: PageGuardInput): PageGuardDecision {
  const { pageType, activeStatus, statusEntries, bootstrapped } = input;

  // Откладывание гейтов на холодной загрузке (см. блок-комментарий выше): никогда не
  // применяем их к пред-авторизационным дефолтам, иначе валидный deep-link будет затёрт.
  if (!bootstrapped) return { action: 'allow' };

  // Контекст, выводимый из страницы (ADR-0005 Phase C): страница, уникальная для ДРУГОЙ
  // capability пользователя, переключает контекст, а не отбрасывает.
  const pageCtx = pageContextOf(pageType);
  const hasContext = (candidate: CompanyStatus) =>
    statusEntries.some((entry) => entry.status === candidate);
  if (pageCtx && pageCtx !== activeStatus && hasContext(pageCtx)) {
    return { action: 'adopt', context: pageCtx };
  }

  // Кросс-ролевой гейт: покупатель не дотянется до продавецких страниц и наоборот.
  const allowed = activeStatus === 'BUYER' ? BUYER_PAGES : SELLER_PAGES;
  if (!allowed.has(pageType)) return { action: 'bounce', reason: 'context' };

  return { action: 'allow' };
}
