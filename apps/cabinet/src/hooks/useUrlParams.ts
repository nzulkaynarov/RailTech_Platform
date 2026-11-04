import { useCallback, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/**
 * Правка параметров адреса без потерянных обновлений. Функциональная форма `setSearchParams(fn)` считает от параметров
 * последнего ОТРИСОВАННОГО кадра: два быстрых действия подряд (вкладка, затем поиск) затирали друг друга. Здесь база — самый
 * свежий адрес: он же запоминается сразу при вызове, не дожидаясь перерисовки.
 */
export function useUrlParams() {
  const location = useLocation();
  const navigate = useNavigate();
  const latest = useRef(location.search);
  useEffect(() => {
    latest.current = location.search;
  }, [location.search]);
  return useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(latest.current);
      for (const [key, value] of Object.entries(patch)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      const search = next.toString();
      latest.current = search ? `?${search}` : '';
      navigate({ pathname: location.pathname, search: latest.current }, { replace: true });
    },
    [navigate, location.pathname],
  );
}
