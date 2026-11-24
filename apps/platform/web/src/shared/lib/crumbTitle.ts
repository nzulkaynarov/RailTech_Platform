import { useEffect, useSyncExternalStore } from "react";

/**
 * Название открытого объекта для последней «хлебной крошки» (аудит 2026-11-24: крошка «142» вместо названия). Адрес
 * знает только идентификатор; экран, у которого есть карточка, пишет сюда номер или имя. Пока экран не написал — в
 * крошке остаётся идентификатор из адреса.
 */
let current: string | null = null;
const listeners = new Set<() => void>();

function set(next: string | null): void {
  if (current === next) return;
  current = next;
  listeners.forEach((listener) => {
    listener();
  });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Экран карточки: `useCrumbTitle(card?.number)`; при уходе с экрана название снимается. */
export function useCrumbTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (!title) return undefined;
    set(title);
    return () => {
      set(null);
    };
  }, [title]);
}

/** Оболочка: название для последней крошки или `null`. */
export function useCrumbTitleValue(): string | null {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => null,
  );
}
