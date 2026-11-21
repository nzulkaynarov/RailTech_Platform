import { useCallback, useState } from "react";

/**
 * Шаги, которые человек уже покидал: требования показываются на таком шаге, а не на только что открытом. `seed` — шаги,
 * пройденные до открытия формы (продолженный черновик). Смена активного шага вычисляется при отрисовке, без эффекта.
 */
export function useLeftSteps(
  active: string,
  seed: readonly string[] = [],
): { left: ReadonlySet<string>; markLeft: (keys: readonly string[]) => void } {
  const [left, setLeft] = useState<ReadonlySet<string>>(() => new Set(seed));
  const [previous, setPrevious] = useState(active);
  if (previous !== active) {
    setPrevious(active);
    setLeft(new Set(left).add(previous));
  }
  const markLeft = useCallback((keys: readonly string[]) => {
    setLeft((prev) => new Set([...prev, ...keys]));
  }, []);
  return { left, markLeft };
}
