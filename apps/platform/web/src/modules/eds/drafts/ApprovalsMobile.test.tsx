import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupApprovalTests, signIn } from "../../../test/approvalsKit";

// Телефон (390 px): списки — карточками, «Одобрение» и «Согласование» — лист на весь экран с кнопками внизу (UX-оценка P0-4).
setupApprovalTests(390);

describe("КП и согласования на телефоне", () => {
  it("ссылка из очереди с panel=open на телефоне превращается в лист", async () => {
    signIn("director@demo.example");
    const { router } = renderAt(
      `/eds/drafts/${encodeURIComponent("КП-2026/116")}?panel=open&tab=approve`,
    );

    const dialog = await screen.findByRole("dialog", { name: /^Одобрение/ });
    expect(await within(dialog).findByRole("form", { name: "Одобрение КП" })).toBeVisible();
    expect(router.state.location.search).toContain("sheet=approve");
    expect(router.state.location.search).not.toContain("panel=open");
  });

  it("менеджер на телефоне: кнопки «Одобрить КП» на карточке нет", async () => {
    signIn("manager@demo.example");
    renderAt(`/eds/drafts/${encodeURIComponent("КП-2026/115")}`);

    expect(await screen.findByRole("heading", { level: 1, name: "КП-2026/115" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Одобрить КП$/ })).toBeNull();
  });
});
