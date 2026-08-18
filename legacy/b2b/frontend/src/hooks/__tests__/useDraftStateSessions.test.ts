/**
 * Волна 2.3b: сценарии, ради которых `set-state-in-effect` переписан на `useDraftState`.
 *
 * Тесты держат ровно те свойства, которые раньше обеспечивались ручными ref-гардами и
 * эффектами — и терялись, стоило гард забыть (так 18-08 нашёлся дефект «панель платного ИИ
 * исчезает при рефетче карточки»). Проверяем ХУКОВУЮ механику на моделях трёх мест:
 * панель ИИ карточки товара, сессия открытия диалога, выбор строк в реестре.
 */

import { describe, it, expect } from 'vitest';
import { useEffect } from 'react';
import { renderHook, act } from '@testing-library/react';

import { useDraftState } from '../useDraftState';

describe('useDraftState — сессии и ключи выборки', () => {
  it('панель ИИ переживает рефетч ТОЙ ЖЕ карточки (источник — id, не объект)', () => {
    // Каждый рефетч ['product', id] отдаёт НОВЫЙ объект с тем же id: раньше пересадка шла по
    // ссылке, и результат платного вызова молча исчезал при загрузке фото.
    const { result, rerender } = renderHook(
      ({ card }) => useDraftState(`card:${card.id}`, () => null as string | null),
      { initialProps: { card: { id: 7 } } },
    );

    act(() => result.current[1]('разобранные предложения ИИ'));
    rerender({ card: { id: 7 } }); // тот же товар, новый объект из кэша
    expect(result.current[0]).toBe('разобранные предложения ИИ');

    rerender({ card: { id: 8 } }); // другой товар — панель обязана уйти
    expect(result.current[0]).toBeNull();
  });

  it('состояние диалога обнуляется на КАЖДОМ открытии', () => {
    const { result, rerender } = renderHook(({ open }) => useDraftState(open, () => ''), {
      initialProps: { open: true },
    });

    act(() => result.current[1]('причина возврата'));
    rerender({ open: false });
    rerender({ open: true });

    expect(result.current[0]).toBe('');
  });

  it('выбор строк обнуляется при смене выборки и переживает рефетч той же', () => {
    const key = (page: number, search: string) => `${page}|${search}`;
    const { result, rerender } = renderHook(
      ({ page, search }) => useDraftState(key(page, search), () => new Set<number>()),
      { initialProps: { page: 1, search: '' } },
    );

    act(() => result.current[1](new Set([11, 12])));
    rerender({ page: 1, search: '' });
    expect([...result.current[0]]).toEqual([11, 12]);

    rerender({ page: 2, search: '' });
    expect(result.current[0].size).toBe(0);
  });

  it('пользователь НЕ видит кадра со старым значением после смены источника', () => {
    // Ради этого свойства волна и затевалась. Тонкость, которую тест поймал сразу: тело
    // рендера один раз ВЫПОЛНЯЕТСЯ со старым значением — React отбрасывает этот результат и
    // тут же перерисовывает с новым, поэтому на экран старое не попадает. Значит мерить надо
    // ЗАКОММИЧЕННЫЕ кадры (эффект после коммита), а не вызовы функции-компонента. С `useEffect`
    // вместо корректировки в рендере старое значение как раз коммитится — и мигает.
    const committed: string[] = [];
    const { rerender } = renderHook(
      ({ source }) => {
        const [value] = useDraftState(source, (s) => s);
        useEffect(() => {
          committed.push(value);
        }, [value]);
        return value;
      },
      { initialProps: { source: 'первый' } },
    );

    committed.length = 0;
    rerender({ source: 'второй' });

    expect(committed).not.toContain('первый');
    expect(committed).toEqual(['второй']);
  });
});
