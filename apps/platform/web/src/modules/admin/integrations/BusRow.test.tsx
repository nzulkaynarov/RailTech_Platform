import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppProviders } from "../../../app/providers";
import type { ServiceGroup } from "../../../shared/api/generated/model";
import { AttentionGroupRow } from "./AttentionGroup";

/** Строка «Шина: недоставленные события» (W15-H8b): «Открыть журнал обмена» — только администратору. */
const group: ServiceGroup = {
  id: "bus_dlq:bus_dlq",
  state: "broken",
  owner: "admin",
  action: "open_bus",
  more_actions: ["recheck"],
  headline: "Шина: не доставлено: 3",
  detail: "Откройте журнал обмена: там видно, какому подписчику и почему событие не дошло.",
  affected: [],
  service_keys: ["bus_dlq"],
  titles: ["Шина: недоставленные события"],
  since: "2026-10-28T08:00:00Z",
  technical: ["eds/letter.created: 500"],
  message: null,
  fix_card: null,
  flaps_24h: 0,
};

function row(editable: boolean) {
  render(
    <AppProviders>
      <MemoryRouter>
        <ul>
          <AttentionGroupRow group={group} editable={editable} severity="fail" />
        </ul>
      </MemoryRouter>
    </AppProviders>,
  );
  return screen.getByRole("listitem");
}

describe("Шина: недоставленные события", () => {
  it("администратор: главное действие — ссылка на журнал обмена, «Проверить снова» — запасное", () => {
    const item = row(true);
    expect(within(item).getByText("Сломано")).toBeInTheDocument();
    const open = within(item).getByRole("link", { name: /Открыть журнал обмена/ });
    expect(open).toHaveAttribute("href", "/admin/bus");
    expect(within(item).getByRole("button", { name: /Проверить снова/ })).toBeInTheDocument();
    // главное действие первое
    expect(within(item).getAllByRole("link")[0]).toBe(open);
  });

  it("без права записи в Admin ссылки на журнал нет", () => {
    const item = row(false);
    expect(within(item).queryByRole("link", { name: /Открыть журнал обмена/ })).toBeNull();
  });
});
