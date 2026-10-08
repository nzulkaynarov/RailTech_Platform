import { useEffect, useState } from "react";

export type ApiHealth = "checking" | "ok" | "unavailable";

/** Состояние `GET /health`. Заглушка Фазы 0 — до появления Refine dataProvider. */
export function useApiHealth(fetchImpl: typeof fetch = fetch): ApiHealth {
  const [health, setHealth] = useState<ApiHealth>("checking");

  useEffect(() => {
    const controller = new AbortController();
    fetchImpl("/health", { signal: controller.signal })
      .then((response) => {
        setHealth(response.ok ? "ok" : "unavailable");
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setHealth("unavailable");
        }
      });
    return () => {
      controller.abort();
    };
  }, [fetchImpl]);

  return health;
}
