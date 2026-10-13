/**
 * Первый кадр `useMediaQuery` соответствует РЕАЛЬНОЙ ширине экрана.
 *
 * Дефект (найден триажем правил React Compiler 18-08): хук стартовал с `false` и только эффект
 * подставлял настоящее значение. На телефоне это значило кадр десктопной вёрстки, затем
 * размонтирование десктопного поддерева и монтирование мобильного — прыжок вёрстки и лишние
 * запросы дочерних компонентов на каждом входе. Хук питает `ResponsiveDataTable` и адаптивные
 * части билдера КП, поэтому радиус был максимальный.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useMediaQuery } from '../use-mobile';

function mockMatchMedia(matches: boolean) {
  const listeners = new Set<() => void>();
  const mql = {
    matches,
    media: '',
    addEventListener: (_: string, cb: () => void) => listeners.add(cb),
    removeEventListener: (_: string, cb: () => void) => listeners.delete(cb),
  };
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue(mql));
  return { mql, listeners };
}

afterEach(() => vi.unstubAllGlobals());

describe('useMediaQuery — первый кадр', () => {
  it('на узком экране возвращает true СРАЗУ, без промежуточного десктопного кадра', () => {
    mockMatchMedia(true);
    const frames: boolean[] = [];
    renderHook(() => {
      const value = useMediaQuery('(max-width: 767px)');
      frames.push(value);
      return value;
    });
    expect(frames[0]).toBe(true);
    expect(frames).not.toContain(false);
  });

  it('на широком экране остаётся false и не дёргает лишний рендер', () => {
    mockMatchMedia(false);
    const frames: boolean[] = [];
    renderHook(() => {
      const value = useMediaQuery('(min-width: 1024px)');
      frames.push(value);
      return value;
    });
    expect(frames.every((f) => f === false)).toBe(true);
  });

  it('реагирует на смену ширины после монтирования', () => {
    const { mql, listeners } = mockMatchMedia(false);
    const { result } = renderHook(() => useMediaQuery('(max-width: 767px)'));
    expect(result.current).toBe(false);

    act(() => {
      (mql as { matches: boolean }).matches = true;
      listeners.forEach((cb) => cb());
    });
    expect(result.current).toBe(true);
  });
});
