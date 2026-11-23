import { fireEvent, waitFor, within } from "@testing-library/react";

/** Боковое окно появляется после загрузки профиля и маршрута — ждём его, а не берём сразу. */
export async function panelEl(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.getElementById("pf-context-panel");
    if (!element) throw new Error("боковое окно ещё не появилось");
    return element;
  });
}

/** Блок решения в центре карточки (ЕД-7): форма оплаты, согласования, одобрения, резолюции — не во вкладке окна. */
export async function decisionEl(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.querySelector<HTMLElement>(".pf-dec-center");
    if (!element) throw new Error("блок решения ещё не появился");
    return element;
  });
}

/** Открывает вкладку бокового окна по имени («Сведения», «Маршрут», «История») и отдаёт окно. */
export async function openSideTab(name: string): Promise<HTMLElement> {
  const panel = await panelEl();
  const tab = await within(panel).findByRole("tab", { name });
  fireEvent.click(tab);
  return panel;
}
