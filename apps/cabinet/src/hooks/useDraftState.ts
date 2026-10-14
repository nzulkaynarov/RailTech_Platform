import { useState } from 'react';

/**
 * Состояние формы, которое ПЕРЕСОБИРАЕТСЯ при смене источника (обычно `target` диалога).
 *
 * Заменяет распространённый в проекте антипаттерн `useMemo(() => setDraft(...), [target])`:
 * `useMemo` — не место для побочных эффектов, React вправе выбросить и пересчитать мемо
 * (и делает это в concurrent-рендере), а значит форма могла сброситься в произвольный
 * момент. Правило `react-hooks/set-state-in-render` из eslint-plugin-react-hooks 7 ловит
 * это как «Calling setState from useMemo may trigger an infinite loop» — 10 мест на
 * 2026-08-18.
 *
 * Реализация — официальный паттерн React «adjusting some state when a prop changes»
 * (react.dev/learn/you-might-not-need-an-effect): сравнение с предыдущим источником прямо
 * в рендере. React отбрасывает результат текущего рендера и сразу перерисовывает компонент
 * с новым состоянием, поэтому пользователь промежуточного кадра не видит — в отличие от
 * `useEffect`, который сначала показал бы старую форму, а потом дёрнул второй рендер.
 *
 * Источник сравнивается ПО ССЫЛКЕ: для объектов из React Query это стабильная ссылка на
 * элемент кэша, а `null` (создание новой записи) — стабильный литерал.
 *
 * @example
 * const [draft, setDraft] = useDraftState(target, (t) => t ?? { name: '' });
 */
export function useDraftState<TSource, TDraft>(
  source: TSource,
  build: (source: TSource) => TDraft,
): readonly [TDraft, React.Dispatch<React.SetStateAction<TDraft>>] {
  const [draft, setDraft] = useState<TDraft>(() => build(source));
  const [previousSource, setPreviousSource] = useState(source);

  if (previousSource !== source) {
    setPreviousSource(source);
    setDraft(build(source));
  }

  return [draft, setDraft] as const;
}
