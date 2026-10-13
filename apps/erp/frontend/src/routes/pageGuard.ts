/**
 * Единое решение о доступе к странице (KYC → контекст).
 *
 * Вынесено ЧИСТОЙ функцией, чтобы её можно было покрыть юнит-тестами и чтобы три
 * исторически раздельных guard-эффекта опирались на один источник правды. Наборы страниц
 * берутся из реестра (`config/pageRegistry`) — новая страница не может «потеряться» в одном
 * из них.
 *
 * `bootstrapped` — несущий вход для починки cold-load deep-link: пока `loadFromAuth`
 * не разрешил реальные capabilities (сигнал — `screen === 'main'`), стор держит
 * ПРЕД-авторизационные ДЕФОЛТЫ: kycStatus 'not_started', activeStatus 'BUYER',
 * пустые statusEntries. Применение гейтов к ним на холодном deep-link (`#request-detail/3`,
 * `#deal-quote/7`) ошибочно провалило бы проверки KYC/контекста и отбросило страницу на
 * #dashboard (затерев хэш через replaceState). Поэтому пока `!bootstrapped` — РАЗРЕШАЕМ
 * (откладываем); эффект перезапустится, когда capabilities приедут, и применит гейты
 * ровно как раньше.
 */

import { BUYER_PAGES, KYC_ALLOWED_PAGES, SELLER_PAGES } from '@/config/pageRegistry';
import type { CompanyStatus, CompanyStatusEntry } from '@/store/userStore';

export type PageGuardDecision =
  | { action: 'allow' }
  | { action: 'adopt'; context: CompanyStatus }
  | { action: 'bounce'; reason: 'kyc' | 'context' };

export interface PageGuardInput {
  pageType: string;
  kycStatus: string;
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
  const { pageType, kycStatus, activeStatus, statusEntries, bootstrapped } = input;

  // Откладывание гейтов на холодной загрузке (см. блок-комментарий выше): никогда не
  // применяем их к пред-авторизационным дефолтам, иначе валидный deep-link будет затёрт.
  if (!bootstrapped) return { action: 'allow' };

  // Порог KYC: ниже L2 — только dashboard/profile/settings/help + чтение каталога.
  if (kycStatus !== 'verified' && !KYC_ALLOWED_PAGES.has(pageType)) {
    return { action: 'bounce', reason: 'kyc' };
  }

  // Контекст, выводимый из страницы (ADR-0005 Phase C): страница, уникальная для ДРУГОЙ
  // подтверждённой capability пользователя, переключает контекст, а не отбрасывает.
  const pageCtx = pageContextOf(pageType);
  const hasContext = (candidate: CompanyStatus) =>
    statusEntries.some((entry) => entry.status === candidate && entry.verification === 'verified');
  if (pageCtx && pageCtx !== activeStatus && hasContext(pageCtx)) {
    return { action: 'adopt', context: pageCtx };
  }

  // Кросс-ролевой гейт: покупатель не дотянется до продавецких страниц и наоборот.
  const allowed = activeStatus === 'BUYER' ? BUYER_PAGES : SELLER_PAGES;
  if (!allowed.has(pageType)) return { action: 'bounce', reason: 'context' };

  return { action: 'allow' };
}
