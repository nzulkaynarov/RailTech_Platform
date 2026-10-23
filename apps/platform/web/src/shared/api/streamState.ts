import { useSyncExternalStore } from "react";

/**
 * Жив ли поток подсказок BFF (SSE). Состояние одно на вкладку: его ставит `useEventStream`, читает опрос
 * (`usePollQuery`): при живом потоке опрос редкий, при обрыве возвращается к 30 секундам.
 */
let live = false;
const listeners = new Set<() => void>();

export function setStreamLive(value: boolean): void {
  if (live === value) return;
  live = value;
  listeners.forEach((listener) => {
    listener();
  });
}

export function isStreamLive(): boolean {
  return live;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useStreamLive(): boolean {
  return useSyncExternalStore(subscribe, isStreamLive, () => false);
}
