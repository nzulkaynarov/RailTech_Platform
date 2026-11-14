import { fireEvent, screen } from "@testing-library/react";

/**
 * Формы секциями (`StepSections`, platform-frontend.md §4.1a): открыть секцию, в которой лежит элемент, если она свёрнута.
 * Возвращает сам элемент — удобно оборачивать `getByLabelText`.
 */
export function reveal<T extends HTMLElement>(element: T): T {
  const body = element.closest<HTMLElement>(".pf-fstep-body");
  if (body?.hidden) {
    const head = document.getElementById(body.getAttribute("aria-labelledby") ?? "");
    if (head) fireEvent.click(head);
  }
  return element;
}

/** Открыть секцию по заголовку, если она свёрнута. */
export function openStep(title: string | RegExp): void {
  const name = typeof title === "string" ? new RegExp(`^${title}`) : title;
  const head = screen.queryByRole("button", { name, expanded: false });
  if (head) fireEvent.click(head);
}
