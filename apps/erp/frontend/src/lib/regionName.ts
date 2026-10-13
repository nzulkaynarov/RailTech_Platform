/**
 * Локализованное название страны по коду ISO 3166-1 alpha-2.
 *
 * Почему НЕ словарь ключей i18n. До этой волны названия семи стран лежали в `ru.json`/`en.json`
 * ключами `countries.*`, а справочник вырос до полного перечня ISO (249). Держать 498 строк
 * руками — гарантированный разъезд: любая новая страна печаталась бы в английском интерфейсе
 * по-русски (именно так и вело себя поле страны в карточке компании).
 *
 * `Intl.DisplayNames` (ECMA-402) — стандартный ответ платформы: браузер отдаёт название региона
 * на языке интерфейса из данных CLDR. Ноль ключей, весь перечень, обе локали сразу — и узбекская
 * заработает в тот же день, когда появится в интерфейсе, без правки словарей.
 *
 * Фолбэк — наименование из БД: если среда без ICU или код неизвестен стандарту (оператор завёл
 * свою строку через админку), лучше показать имя из справочника, чем сырой код.
 */

/**
 * Коды, отданные ISO 3166-1 «на усмотрение пользователя» (AA, QM–QZ, XA–XZ, ZZ). Именно ими
 * оператор заведёт свою строку через админку, и именно на них CLDR отвечает не кодом, а
 * заглушкой «неизвестный регион» — показать её вместо введённого названия было бы хуже
 * сырого кода. Для этого диапазона стандарт не авторитет: берём наименование из справочника.
 */
const USER_ASSIGNED_CODE = /^(AA|Q[M-Z]|X[A-Z]|ZZ)$/;

const cache = new Map<string, Intl.DisplayNames | null>();

function displayNames(language: string): Intl.DisplayNames | null {
  const locale = language.split('-')[0] || 'ru';
  if (!cache.has(locale)) {
    try {
      cache.set(locale, new Intl.DisplayNames([locale], { type: 'region' }));
    } catch {
      cache.set(locale, null);
    }
  }
  return cache.get(locale) ?? null;
}

/**
 * Название страны на языке интерфейса.
 *
 * @param code код ISO alpha-2 (`country.code` / `country.alpha2`)
 * @param language текущий язык i18n (`i18n.language`)
 * @param fallback наименование из справочника — показываем, когда стандарт кода не знает
 */
export function regionName(
  code: string | null | undefined,
  language: string,
  fallback = '',
): string {
  const alpha2 = (code || '').trim().toUpperCase();
  if (alpha2.length !== 2 || USER_ASSIGNED_CODE.test(alpha2)) return fallback || alpha2;
  const resolved = displayNames(language)?.of(alpha2);
  // Intl возвращает САМ КОД, когда региона нет в CLDR — это не название, а признак промаха.
  if (!resolved || resolved === alpha2) return fallback || alpha2;
  return resolved;
}
