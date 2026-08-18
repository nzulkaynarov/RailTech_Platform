/**
 * `useDraftState` — пересборка формы при смене источника без побочного эффекта в `useMemo`.
 *
 * Замена антипаттерна `useMemo(() => setDraft(target), [target])` (10 мест на 18-08). Тест
 * держит три свойства, ради которых хук и появился: правки пользователя переживают ререндер
 * с ТЕМ ЖЕ источником; смена источника пересобирает черновик; смена источника НЕ теряется,
 * даже если до неё пользователь успел напечатать.
 */

import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useDraftState } from '../useDraftState';

type Target = { id: number; name: string } | null;

const build = (target: Target) => ({ name: target?.name ?? '' });

describe('useDraftState', () => {
  it('строит черновик из источника на первом рендере', () => {
    const { result } = renderHook(() => useDraftState<Target, { name: string }>({ id: 1, name: 'Рельсы' }, build));
    expect(result.current[0]).toEqual({ name: 'Рельсы' });
  });

  it('сохраняет правки пользователя при ререндере с ТЕМ ЖЕ источником', () => {
    const target: Target = { id: 1, name: 'Рельсы' };
    const { result, rerender } = renderHook(({ src }) => useDraftState<Target, { name: string }>(src, build), {
      initialProps: { src: target },
    });

    act(() => result.current[1]({ name: 'Рельсы Р65' }));
    expect(result.current[0]).toEqual({ name: 'Рельсы Р65' });

    rerender({ src: target });
    expect(result.current[0]).toEqual({ name: 'Рельсы Р65' });
  });

  it('пересобирает черновик при смене источника — даже поверх правок', () => {
    const { result, rerender } = renderHook(({ src }) => useDraftState<Target, { name: string }>(src, build), {
      initialProps: { src: { id: 1, name: 'Рельсы' } as Target },
    });

    act(() => result.current[1]({ name: 'напечатано и не сохранено' }));
    rerender({ src: { id: 2, name: 'Шпалы' } as Target });

    expect(result.current[0]).toEqual({ name: 'Шпалы' });
  });

  it('null-источник (создание новой записи) даёт пустой черновик', () => {
    const { result, rerender } = renderHook(({ src }) => useDraftState<Target, { name: string }>(src, build), {
      initialProps: { src: { id: 1, name: 'Рельсы' } as Target },
    });

    rerender({ src: null });
    expect(result.current[0]).toEqual({ name: '' });
  });
});
