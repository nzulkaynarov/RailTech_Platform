import { useEffect } from 'react';

/**
 * Открыть карточку документа по ссылке вида `#acts?open=4`.
 *
 * Такие ссылки строят письма, уведомления, глобальный поиск (⌘K) и панели «после контракта».
 * Раньше каждая страница разбирала параметр сама — и по-разному: счета делали это правильно
 * (разбор при монтировании И на `hashchange`, затем чистка параметра), договоры — только при
 * монтировании (поэтому переход из поиска, когда ты УЖЕ на странице договоров, не открывал
 * ничего), а страница актов не разбирала его вовсе — акт по ссылке не открывался НИКОГДА.
 * Найдено прогоном глазами 19-08.
 *
 * Хук закрывает все три случая одним поведением: читает при монтировании, слушает `hashchange`
 * и СНИМАЕТ параметр после применения — иначе ручное закрытие карточки или перезагрузка
 * открывали бы её снова, а адрес хранил бы мусор.
 *
 * @param hash    базовый хеш страницы без параметров (например `acts`)
 * @param onOpen  что сделать с распознанным id
 */
export function useHashOpenParam(hash: string, onOpen: (id: number) => void): void {
  useEffect(() => {
    const applyDeepLink = () => {
      const query = window.location.hash.split('?')[1];
      const raw = query ? new URLSearchParams(query).get('open') : null;
      const parsed = raw ? Number(raw) : NaN;
      if (!Number.isFinite(parsed) || parsed <= 0) return;
      onOpen(parsed);
      window.history.replaceState(
        { ...(window.history.state || {}) },
        '',
        `${window.location.pathname}${window.location.search}#${hash}`,
      );
    };
    applyDeepLink();
    window.addEventListener('hashchange', applyDeepLink);
    return () => window.removeEventListener('hashchange', applyDeepLink);
    // `onOpen` намеренно вне списка: страницы передают стабильный сеттер состояния, а перевешивать
    // слушатель на каждый рендер незачем.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hash]);
}
