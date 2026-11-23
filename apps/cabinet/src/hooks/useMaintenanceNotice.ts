import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  DISMISS_MS,
  maintenanceView,
  parseNotice,
  type MaintenanceNotice,
  type MaintenanceView,
} from '@/lib/maintenance';
import { useNow } from '@/hooks/useNow';

export const MAINTENANCE_URL = '/maintenance.json';
export const MAINTENANCE_POLL_MS = 60_000;
/** Не запрос к порталу: файл отдаёт статика (Caddy), поэтому ключ свой. */
export const MAINTENANCE_KEY = ['maintenance-notice'] as const;
const DISMISS_KEY = 'rt.maintenance.dismissed';

/**
 * Читает `/maintenance.json`: нет файла (404), не JSON (SPA отдаёт index.html) и мусор — `null`. Сбой сети бросает
 * ошибку: запрос сохраняет прежний ответ (во время выкладки связь пропадает, баннер при этом не гаснет).
 */
export async function fetchMaintenance(): Promise<MaintenanceNotice | null> {
  const response = await fetch(MAINTENANCE_URL, { cache: 'no-store' });
  if (!response.ok) return null;
  try {
    return parseNotice(await response.json());
  } catch {
    return null;
  }
}

function readDismissed(startsAt: number | undefined): number {
  if (startsAt === undefined) return 0;
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(DISMISS_KEY) ?? 'null') as {
      startsAt?: number;
      until?: number;
    } | null;
    return saved?.startsAt === startsAt && typeof saved.until === 'number' ? saved.until : 0;
  } catch {
    return 0;
  }
}

export interface MaintenanceState {
  view: MaintenanceView | null;
  dismiss: () => void;
}

/**
 * Предупреждение о плановом обновлении (DECISIONS 2026-11-23): опрос при старте, раз в минуту и при возврате в окно
 * (в скрытой вкладке опроса нет), время идёт само. Когда выкладка сняла файл посреди работ — страница перезагружается.
 */
export function useMaintenanceNotice(
  reload: () => void = () => {
    window.location.reload();
  },
): MaintenanceState {
  const query = useQuery({
    queryKey: MAINTENANCE_KEY,
    queryFn: fetchMaintenance,
    refetchInterval: MAINTENANCE_POLL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: 'always',
    staleTime: 0,
    retry: false,
  });
  const notice = query.data ?? null;
  const now = useNow(15_000);

  const [dismissedUntil, setDismissedUntil] = useState(0);
  const startsAt = notice?.startsAt;
  const until = Math.max(dismissedUntil, readDismissed(startsAt));
  const view = maintenanceView(notice, now, until);

  const wasRunning = useRef(false);
  useEffect(() => {
    if (view?.phase === 'running') wasRunning.current = true;
  }, [view?.phase]);
  useEffect(() => {
    if (query.isSuccess && notice === null && wasRunning.current) {
      wasRunning.current = false;
      reload();
    }
  }, [query.isSuccess, notice, reload]);

  const dismiss = useCallback(() => {
    const next = Date.now() + DISMISS_MS;
    setDismissedUntil(next);
    try {
      window.sessionStorage.setItem(DISMISS_KEY, JSON.stringify({ startsAt, until: next }));
    } catch {
      /* хранилище недоступно — скрытие живёт до перезагрузки */
    }
  }, [startsAt]);

  return { view, dismiss };
}
