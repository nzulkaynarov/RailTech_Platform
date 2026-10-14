/**
 * Один обход постраничного ответа DRF — для экранов, которые показывают список ЦЕЛИКОМ.
 *
 * Операторские реестры считают по списку счётчики вкладок и плашки «Всего», а пейджера в
 * интерфейсе у них нет. Если брать только первую страницу, оператор видит 20 записей из 42 и
 * счётчики, посчитанные по этим же двадцати, — то есть неправду, неотличимую от правды.
 *
 * Отдельный модуль, потому что таких обходов в коде было ТРИ копии (`catalogApi.fetchAllPages`
 * и два инлайновых цикла в `accountsApi`). Ровно этот класс — «две копии механики, починка
 * дошла до одной» — уже стоил проекта дважды (ленты событий, экраны отказа по КП).
 *
 * `page_size` берём максимальный, который разрешает `core.pagination.DefaultPageNumberPagination`
 * (200): один запрос вместо десяти при том же результате. Потолок `MAX_PAGES` — предохранитель
 * от бесконечной цепочки `next`, а не бизнес-ограничение.
 *
 * Предел применимости: обход держит операторские объёмы (сотни строк). Реестру, который дорастёт
 * до тысяч, нужна серверная постраничка вместе с серверными счётчиками вкладок —
 * `AdminDataTable` постраничку уже умеет (`pagination`), не хватает только счётчиков.
 */

import { apiClient } from './client';
import type { PaginatedResponse } from './types';

/** Максимум, который принимает `DefaultPageNumberPagination.max_page_size`. */
export const MAX_PAGE_SIZE = 200;

const MAX_PAGES = 500;

export async function fetchAllPages<T>(
  url: string,
  params?: Record<string, unknown>,
  /** Доп. настройки запроса (заголовки). */
  config?: { headers?: Record<string, string> },
): Promise<T[]> {
  const all: T[] = [];
  let nextUrl: string | null = url;
  let isFirst = true;
  let guard = 0;

  while (nextUrl && guard < MAX_PAGES) {
    // Свежая const на итерацию: держит аргумент запроса вне цикла переприсваивания
    // (`nextUrl` ← next ← data ← nextUrl), который сбивает вывод типов TS (TS7022).
    const currentUrl: string = nextUrl;
    const response = await apiClient.get<PaginatedResponse<T> | T[]>(currentUrl, {
      ...(config ?? {}),
      // Параметры нужны только первому запросу: ссылка `next` уже несёт их в себе.
      ...(isFirst ? { params: { ...(params ?? {}), page_size: MAX_PAGE_SIZE } } : {}),
    });
    // Часть вьюсетов отключает постраничку (`pagination_class = None`) и отдаёт голый массив.
    // Обход должен переживать оба ответа: иначе вызывающий код падал бы при перестановке
    // настройки на бэкенде, а не просто отдавал меньше строк.
    const payload = response.data;
    if (Array.isArray(payload)) return payload;
    all.push(...payload.results);
    const rawNext: string | null = payload.next;
    // `next` — абсолютный URL, а baseURL клиента уже указывает на корень API.
    nextUrl = rawNext ? rawNext.replace(/^.*\/api\/v1\//, '') : null;
    isFirst = false;
    guard += 1;
  }
  return all;
}
