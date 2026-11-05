import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import type { TelegramStatus } from '@/api/portal';
import { useTelegramStatus } from '@/api/queries';
import { useAppMode, type AppMode } from '@/session/mode';

/**
 * Шаг «Подключить Telegram» (ADR-0023 п. 3, NOTIFY-1) — логика без вида.
 *
 * Сейчас его показывает плашка после входа (`components/TelegramBanner.tsx`, только состояние `todo`); чек-лист «Первые
 * шаги» (волна J1) возьмёт этот же хук и нарисует шаг с отметкой «сделано» / «позже» — без переписывания логики.
 *
 * Состояния:
 * - `todo` — можно и стоит подключить (веб, ссылку выпустить можно, Telegram не привязан, «позже» не действует);
 * - `done` — Telegram привязан (по проекции CRM, `GET /me/telegram`);
 * - `snoozed` — контакт нажал «Позже» в этом браузере, шаг вернётся через 14 дней;
 * - `hidden` — шаг не для этой сессии: Telegram Mini App (Telegram уже есть) или подключить нельзя (`available=false`);
 * - `loading` — статус ещё не пришёл.
 *
 * «Позже» — удобство одного устройства, не настройка контакта, поэтому localStorage; недоступное хранилище (приватный
 * режим) значит «показывать», а не ошибку.
 */
export type TelegramStepState = 'loading' | 'todo' | 'done' | 'snoozed' | 'hidden';

export const TELEGRAM_BANNER_SNOOZE_KEY = 'rt-cab-tg-banner-snooze';
export const TELEGRAM_BANNER_SNOOZE_MS = 14 * 24 * 60 * 60 * 1000;

/** Состояние перехода в Профиль из шага: Профиль сразу выпускает ссылку привязки. */
export interface ConnectTelegramState {
  connectTelegram: true;
}

export function bannerSnoozed(now: number): boolean {
  try {
    const until = Number(localStorage.getItem(TELEGRAM_BANNER_SNOOZE_KEY));
    return Number.isFinite(until) && until > now;
  } catch {
    return false;
  }
}

export function snoozeBanner(now: number): void {
  try {
    localStorage.setItem(TELEGRAM_BANNER_SNOOZE_KEY, String(now + TELEGRAM_BANNER_SNOOZE_MS));
  } catch {
    // Хранилище недоступно — шаг скрыт до перезагрузки страницы.
  }
}

/** Чистое правило состояния шага (тестируется без React). */
export function telegramStepState(input: {
  mode: AppMode;
  snoozed: boolean;
  status: TelegramStatus | undefined;
}): TelegramStepState {
  if (input.mode !== 'web') return 'hidden';
  if (!input.status) return input.snoozed ? 'snoozed' : 'loading';
  if (input.status.linked) return 'done';
  if (!input.status.available) return 'hidden';
  return input.snoozed ? 'snoozed' : 'todo';
}

export interface TelegramStep {
  state: TelegramStepState;
  /** Перейти в Профиль → «Уведомления» и сразу выпустить ссылку. */
  connect: () => void;
  /** «Позже»: скрыть шаг на 14 дней в этом браузере. */
  snooze: () => void;
}

/**
 * Шаг «Подключить Telegram» для сессии. `enabled=false` — статус не запрашивается (например, на самом Профиле);
 * в Mini App статус не запрашивается никогда.
 */
export function useTelegramStep({ enabled = true }: { enabled?: boolean } = {}): TelegramStep {
  const mode = useAppMode();
  const navigate = useNavigate();
  const [snoozed, setSnoozed] = useState(() => bannerSnoozed(Date.now()));
  const status = useTelegramStatus({ enabled: enabled && mode === 'web' && !snoozed });
  const state = telegramStepState({ mode, snoozed, status: status.data });

  const connect = useCallback(() => {
    const next: ConnectTelegramState = { connectTelegram: true };
    navigate({ pathname: '/profile', hash: '#notifications' }, { state: next });
  }, [navigate]);
  const snooze = useCallback(() => {
    snoozeBanner(Date.now());
    setSnoozed(true);
  }, []);

  return { state, connect, snooze };
}
