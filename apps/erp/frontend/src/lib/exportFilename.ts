/**
 * Имя файла выгрузки: `<ресурс>-<дата>.<формат>`.
 *
 * Отдельный модуль, потому что имя задаёт КЛИЕНТ. Скачивание идёт авторизованным запросом и
 * сохраняется как blob, а у blob-ссылки нет `Content-Disposition` от сервера — атрибут
 * `download` берёт ровно то, что мы передали. Без явного имени браузер сохранил бы файл как
 * `export` или как случайный идентификатор blob.
 *
 * Дата в имени нужна, чтобы две выгрузки одного реестра не сливались в `companies (1).csv`:
 * оператор выгружает один и тот же список по многу раз, и разбирать их потом не по чему.
 */
export function exportFilename(pathname: string, fmt: 'csv' | 'xlsx'): string {
  // `/api/v1/accounts/companies/export/` → `companies`
  const segments = pathname.split('/').filter(Boolean);
  const exportIndex = segments.lastIndexOf('export');
  const resource = (exportIndex > 0 ? segments[exportIndex - 1] : segments[segments.length - 1]) || 'export';
  const today = new Date().toISOString().slice(0, 10);
  return `${resource}-${today}.${fmt}`;
}
