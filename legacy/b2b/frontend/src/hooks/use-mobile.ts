import * as React from "react"

const MOBILE_BREAKPOINT = 768

// Reactive media-query flag. Subscribes to a matchMedia query and re-renders when it
// flips. SSR-safe (returns false until mounted). Reused by useIsMobile and the КП builder's
// responsive economics rail / cost-column gates.
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = React.useState<boolean>(false)

  React.useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    mql.addEventListener("change", onChange)
    setMatches(mql.matches)
    return () => mql.removeEventListener("change", onChange)
  }, [query])

  return matches
}

export function useIsMobile() {
  return useMediaQuery(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
}
