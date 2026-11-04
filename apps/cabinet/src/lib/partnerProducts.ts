import type { PartnerCardStatus, PartnerProduct, PriceListRowIssue } from '@/api/portal';

/**
 * «Мои товары» (PART-2): вкладки по статусам, выбор карточек, тексты замечаний. Вся логика статусов, свежести цены и
 * полноты — в ERP; здесь только раскладка ответа по экрану.
 */
export const PARTNER_TABS = ['all', 'draft', 'review', 'returned', 'published', 'matched'] as const;
export type PartnerTab = (typeof PARTNER_TABS)[number];

export const PARTNER_PAGE_SIZE = 20;
/** Один запрос «отправить / подтвердить» ERP принимает не больше стольких карточек (контракт). */
export const PARTNER_BATCH = 500;

export function parseTab(value: string | null): PartnerTab {
  return (PARTNER_TABS as readonly string[]).includes(value ?? '') ? (value as PartnerTab) : 'all';
}

/** Фильтр списка для вкладки: «Все» — без фильтра. */
export function tabStatus(tab: PartnerTab): PartnerCardStatus | undefined {
  return tab === 'all' ? undefined : tab;
}

/** Выбрать можно карточку, которую есть что отправить (свой черновик или возвращённая) или у которой есть своя цена. */
export function selectable(item: Pick<PartnerProduct, 'can_submit' | 'offer'>): boolean {
  return item.can_submit || item.offer !== null;
}

/** Выбранные карточки → что именно делать с ними: отправить на проверку / подтвердить цены. */
export function splitSelection(items: PartnerProduct[], selected: ReadonlySet<number>) {
  const chosen = items.filter((item) => selected.has(item.id));
  return {
    chosen,
    submit: chosen.filter((item) => item.can_submit).map((item) => item.id),
    confirm: chosen.filter((item) => item.offer !== null).map((item) => item.id),
  };
}

/** Подпись поля замечания возврата → ключ i18n `partner.fields.<поле>`. */
export function fieldLabelKey(field: string): string {
  return `partner.fields.${field}`;
}

/**
 * Что исправить в строке файла: ключ `partner.issues.<КОД>` с подстановкой поля и значения. Незнакомый код — общий текст
 * «строка не загружена» (ERP может добавить новые коды раньше, чем их узнает Cabinet).
 */
export function issueKey(issue: Pick<PriceListRowIssue, 'code'>, known: (key: string) => boolean): string {
  const own = `partner.issues.${issue.code}`;
  return known(own) ? own : 'partner.issues.UNKNOWN';
}

/** Постраничный обход списка вкладки (для «отправить все черновики»): id всех карточек, не больше `limit`. */
export function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let start = 0; start < items.length; start += size) out.push(items.slice(start, start + size));
  return out;
}
