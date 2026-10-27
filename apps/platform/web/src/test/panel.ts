import { waitFor } from "@testing-library/react";

/** Боковое окно появляется после загрузки профиля и маршрута — ждём его, а не берём сразу. */
export async function panelEl(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.getElementById("pf-context-panel");
    if (!element) throw new Error("боковое окно ещё не появилось");
    return element;
  });
}
