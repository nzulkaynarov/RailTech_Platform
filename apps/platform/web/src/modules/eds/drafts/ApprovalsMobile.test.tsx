import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupApprovalTests, signIn } from "../../../test/approvalsKit";

// Телефон (390 px): списки — карточками, «Одобрение» и «Согласование» — лист на весь экран с кнопками внизу (UX-оценка P0-4).
setupApprovalTests(390);

describe("КП и согласования на телефоне", () => {
  it("КП: строка открывает лист «Одобрение» на весь экран, а не окно каркаса; «Закрыть» закрывает", async () => {
    signIn("director@demo.example");
    const { router } = renderAt("/eds/drafts");
    expect(await screen.findByRole("list", { name: "КП на одобрение" })).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: "Показать КП КП-2026/115 в боковом окне" }));

    const dialog = await screen.findByRole("dialog", { name: /^Одобрение/ });
    expect(router.state.location.search).toContain("sheet=approve");
    expect(router.state.location.search).not.toContain("panel=open");
    expect(await within(dialog).findByRole("form", { name: "Одобрение КП" })).toBeVisible();
    expect(
      within(dialog).getByRole("button", { name: "Одобрить КП → отправить клиенту" }),
    ).toBeVisible();
    expect(dialog.closest(".ant-drawer-bottom")).not.toBeNull();
    expect(within(dialog).getByRole("form").querySelector(".pf-dec-actions")).not.toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

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

  it("служебка: строка открывает лист «Согласование» с тремя кнопками внизу", async () => {
    signIn("director@demo.example");
    renderAt("/eds/approvals");
    expect(await screen.findByRole("list", { name: "Документы на согласовании" })).toBeVisible();

    fireEvent.click(
      screen.getByRole("link", { name: "Показать документ СЗ-2026/014 в боковом окне" }),
    );

    const dialog = await screen.findByRole("dialog", { name: /^Согласование/ });
    expect(
      await within(dialog).findByRole("form", { name: "Согласование документа" }),
    ).toBeVisible();
    for (const name of ["Согласовать", "Вернуть на доработку", "Отклонить"]) {
      expect(within(dialog).getByRole("button", { name })).toBeVisible();
    }
    expect(within(dialog).getByRole("form").querySelector(".pf-dec-actions")).not.toBeNull();
  });

  it("менеджер на телефоне: кнопки «Одобрить КП» на карточке нет", async () => {
    signIn("manager@demo.example");
    renderAt(`/eds/drafts/${encodeURIComponent("КП-2026/115")}`);

    expect(await screen.findByRole("heading", { level: 1, name: "КП-2026/115" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Одобрить КП$/ })).toBeNull();
  });
});
