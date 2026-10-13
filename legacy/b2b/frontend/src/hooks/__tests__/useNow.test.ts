/**
 * `useNow` — «сейчас» как значение, за которым компонент следит.
 *
 * Заменяет `Date.now()` прямо в рендере (react-hooks/purity, 3 места на 18-08). Помимо
 * чистоты рендера хук чинит замирающие счётчики: до него «просроченные КП» и «дней до конца
 * подписки» показывали время последнего рендера, а во вкладке, открытой с утра, это утро.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useNow } from '../useNow';

describe('useNow', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('возвращает текущее время сразу', () => {
    vi.setSystemTime(new Date('2026-08-18T10:00:00Z'));
    const { result } = renderHook(() => useNow());
    expect(result.current).toBe(Date.now());
  });

  it('обновляется по таймеру — счётчик не замирает', () => {
    vi.setSystemTime(new Date('2026-08-18T10:00:00Z'));
    const { result } = renderHook(() => useNow(60_000));
    const first = result.current;

    act(() => {
      vi.setSystemTime(new Date('2026-08-18T10:02:00Z'));
      vi.advanceTimersByTime(60_000);
    });

    expect(result.current).toBeGreaterThan(first);
  });

  it('снимает интервал при размонтировании (без утечки таймеров)', () => {
    const clearSpy = vi.spyOn(window, 'clearInterval');
    const { unmount } = renderHook(() => useNow(1_000));
    unmount();
    expect(clearSpy).toHaveBeenCalled();
    clearSpy.mockRestore();
  });

  it('tickMs <= 0 отключает таймер (время фиксируется на монтировании)', () => {
    vi.setSystemTime(new Date('2026-08-18T10:00:00Z'));
    const { result } = renderHook(() => useNow(0));
    const first = result.current;

    act(() => {
      vi.setSystemTime(new Date('2026-08-18T11:00:00Z'));
      vi.advanceTimersByTime(3_600_000);
    });

    expect(result.current).toBe(first);
  });
});
