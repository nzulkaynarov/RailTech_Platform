import { App } from "antd";
import { useContext, useEffect, useId, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { UNSAFE_DataRouterContext, useBlocker } from "react-router";

/**
 * Очередь несохранённых форм на экране. React Router держит один блокировщик перехода на роутер (второй — с
 * предупреждением, и спрашивает только последний), поэтому вопрос задаёт первая несохранённая форма, остальные ждут
 * очереди: в Профиле две формы, вопрос при уходе — один.
 */
const queue: string[] = [];
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function head(): string | undefined {
  return queue[0];
}

function enqueue(id: string): () => void {
  queue.push(id);
  listeners.forEach((listener) => {
    listener();
  });
  return () => {
    const index = queue.indexOf(id);
    if (index >= 0) queue.splice(index, 1);
    listeners.forEach((listener) => {
      listener();
    });
  };
}

export interface UnsavedGuardProps {
  /** Есть несохранённые изменения — переход с экрана и закрытие вкладки спрашивают */
  when: boolean;
  /** Идёт сохранение: переход — его итог (новая роль открывается по своему адресу), вопроса нет */
  busy?: boolean;
  /**
   * Параметры адреса, смена которых — тоже уход из формы: раздел бота (`section`), вкладка «Компании» (`tab`),
   * выбранная роль (`role`). Смена окна и его вкладки (`?panel=`, `?tab=` окна) вопроса не вызывает.
   */
  params?: readonly string[];
  /** Поднят — переход без вопроса: «Отменить» в баре сам закрывает форму (новая роль), спрашивать нечего */
  skipRef?: { readonly current: boolean };
}

/**
 * Несохранённые изменения формы (аудит 2026-10-30, A1): при уходе с экрана — вопрос «Выйти без сохранения?», при
 * закрытии вкладки — предупреждение браузера. Встроен в `ContextualSaveBar` (у каждой формы с баром); форма без бара
 * ставит его сама. Вне роутера данных (тест общего компонента) — только предупреждение браузера.
 */
export function UnsavedGuard({
  when,
  busy = false,
  params = ["section"],
  skipRef,
}: UnsavedGuardProps) {
  const id = useId();
  const dataRouter = useContext(UNSAFE_DataRouterContext);
  const owner = useSyncExternalStore(subscribe, head, head);

  useEffect(() => {
    if (!when) return;
    return enqueue(id);
  }, [when, id]);

  useEffect(() => {
    if (!when) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => {
      window.removeEventListener("beforeunload", handler);
    };
  }, [when]);

  return when && owner === id && dataRouter ? (
    <Blocker busy={busy} params={params} skipRef={skipRef} />
  ) : null;
}

function Blocker({
  busy,
  params,
  skipRef,
}: {
  busy: boolean;
  params: readonly string[];
  skipRef?: { readonly current: boolean };
}) {
  const { t } = useTranslation("ui");
  const { modal } = App.useApp();
  // Роутер спрашивает функцию последней отрисовки (useBlocker обновляет её после каждой).
  const blocker = useBlocker(({ currentLocation, nextLocation }) => {
    if (busy || skipRef?.current) return false;
    if (currentLocation.pathname !== nextLocation.pathname) return true;
    const from = new URLSearchParams(currentLocation.search);
    const to = new URLSearchParams(nextLocation.search);
    return params.some((name) => from.get(name) !== to.get(name));
  });

  useEffect(() => {
    if (blocker.state !== "blocked") return;
    modal.confirm({
      title: t("unsavedGuard.title"),
      content: t("unsavedGuard.text"),
      okText: t("unsavedGuard.leave"),
      cancelText: t("unsavedGuard.stay"),
      okButtonProps: { danger: true },
      onOk: () => {
        blocker.proceed();
      },
      onCancel: () => {
        blocker.reset();
      },
    });
  }, [blocker, modal, t]);

  return null;
}
