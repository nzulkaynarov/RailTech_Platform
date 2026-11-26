import { useCallback, useEffect, useId, useSyncExternalStore } from "react";
import { useNavigate, useSearchParams } from "react-router";

/**
 * Слой «на весь экран» живёт в адресе: `?view=full&page=N`. «Назад» в браузере сворачивает слой, ссылку можно отправить
 * коллеге. Если на странице несколько просмотров, слой открывает один — тот, кто первым занял адрес (кнопка или первый
 * смонтированный после перезагрузки).
 */
const store = { owner: null as string | null, subscribers: new Set<() => void>() };
function claim(id: string | null) {
  store.owner = id;
  store.subscribers.forEach((notify) => {
    notify();
  });
}
function subscribe(notify: () => void) {
  store.subscribers.add(notify);
  return () => {
    store.subscribers.delete(notify);
  };
}

export const VIEW_PARAM = "view";
export const PAGE_PARAM = "page";

/** Состояние адреса одного просмотра. `pushed` — открыт из этой страницы (тогда «Свернуть» = шаг назад). */
const pushedBy = new Set<string>();

export function useFullRoute() {
  const id = useId();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const wants = params.get(VIEW_PARAM) === "full";
  const owner = useSyncExternalStore(
    subscribe,
    () => store.owner,
    () => null,
  );
  useEffect(() => {
    if (wants && store.owner === null) claim(id);
    if (!wants && store.owner === id) {
      pushedBy.delete(id);
      claim(null);
    }
  }, [wants, id, owner]);
  useEffect(
    () => () => {
      pushedBy.delete(id);
      if (store.owner === id) claim(null);
    },
    [id],
  );

  const open = wants && owner === id;
  const page = Math.max(1, Number(params.get(PAGE_PARAM)) || 1);

  const openFull = useCallback(
    (from: number) => {
      claim(id);
      pushedBy.add(id);
      setParams((previous) => {
        const next = new URLSearchParams(previous);
        next.set(VIEW_PARAM, "full");
        next.set(PAGE_PARAM, String(from));
        return next;
      });
    },
    [id, setParams],
  );
  const close = useCallback(() => {
    if (pushedBy.has(id)) {
      pushedBy.delete(id);
      void navigate(-1);
      return;
    }
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete(VIEW_PARAM);
        next.delete(PAGE_PARAM);
        return next;
      },
      { replace: true },
    );
  }, [id, navigate, setParams]);
  const setPage = useCallback(
    (to: number) => {
      setParams(
        (previous) => {
          if (previous.get(PAGE_PARAM) === String(to)) return previous;
          const next = new URLSearchParams(previous);
          next.set(PAGE_PARAM, String(to));
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  return { open, page, openFull, close, setPage };
}
