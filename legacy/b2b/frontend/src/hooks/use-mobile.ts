import * as React from "react"

const MOBILE_BREAKPOINT = 768

// Reactive media-query flag. Subscribes to a matchMedia query and re-renders when it
// flips. SSR-safe (returns false until mounted). Reused by useIsMobile and the КП builder's
// responsive economics rail / cost-column gates.
export function useMediaQuery(query: string): boolean {
  // Начальное значение читается СРАЗУ, в ленивом инициализаторе. Раньше стартовое `false`
  // означало «десктоп» на первом закоммиченном кадре даже на телефоне: `ResponsiveDataTable`
  // и адаптивные части билдера КП монтировали десктопное дерево, эффект тут же переключал
  // флаг — и всё поддерево размонтировалось и монтировалось заново (прыжок вёрстки + лишние
  // запросы дочерних компонентов на каждом входе). Найдено триажем правил React Compiler 18-08.
  const [matches, setMatches] = React.useState<boolean>(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  )

  React.useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    mql.addEventListener("change", onChange)
    // Один синк после подписки: между рендером и эффектом ширина могла измениться.
    if (mql.matches !== matches) setMatches(mql.matches)
    return () => mql.removeEventListener("change", onChange)
    // `matches` намеренно вне списка: эффект — подписка на query, а не на текущее значение.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  return matches
}

export function useIsMobile() {
  return useMediaQuery(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
}
