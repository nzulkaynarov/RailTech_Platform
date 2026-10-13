/**
 * `useLatestRef` — «последнее значение» для стабильных колбэков без записи в ref во время рендера.
 *
 * Тест держит и свойство (после коммита в ссылке свежее), и ГРАНИЦУ применимости (во время
 * рендера там значение предыдущего коммита — поэтому в разметке ref читать нельзя). Граница
 * важнее свойства: именно её нарушение в загрузке Excel правило `react-hooks/refs` и поймало.
 */

import { describe, it, expect } from 'vitest';
import { useCallback } from 'react';
import { renderHook, act } from '@testing-library/react';

import { useLatestRef } from '../useLatestRef';

describe('useLatestRef', () => {
  it('после коммита колбэк видит СВЕЖЕЕ значение, оставаясь тем же самым', () => {
    const { result, rerender } = renderHook(
      ({ value }) => {
        const ref = useLatestRef(value);
        const read = useCallback(() => ref.current, [ref]);
        return { read };
      },
      { initialProps: { value: 'первое' } },
    );

    const firstCallback = result.current.read;
    expect(result.current.read()).toBe('первое');

    rerender({ value: 'второе' });

    expect(result.current.read).toBe(firstCallback); // колбэк не пересоздался
    expect(result.current.read()).toBe('второе'); // но читает свежее
  });

  it('ВО ВРЕМЯ РЕНДЕРА в ссылке лежит значение предыдущего коммита', () => {
    // Ради этого и существует правило: если от `ref.current` зависит разметка, кнопка может
    // не появиться — рендер прочитает прошлое. Такое значение должно быть состоянием.
    const seenDuringRender: string[] = [];
    const { rerender } = renderHook(
      ({ value }) => {
        const ref = useLatestRef(value);
        seenDuringRender.push(ref.current);
        return null;
      },
      { initialProps: { value: 'первое' } },
    );

    rerender({ value: 'второе' });

    expect(seenDuringRender[0]).toBe('первое'); // на первом рендере — начальное
    expect(seenDuringRender[seenDuringRender.length - 1]).toBe('первое'); // на втором — ещё ПРОШЛОЕ
  });

  it('обновление ссылки не вызывает лишнего рендера', () => {
    let renders = 0;
    const { rerender } = renderHook(
      ({ value }) => {
        renders += 1;
        useLatestRef(value);
      },
      { initialProps: { value: 1 } },
    );

    const before = renders;
    act(() => rerender({ value: 2 }));

    expect(renders).toBe(before + 1); // ровно один рендер на смену пропса, без каскада
  });
});
