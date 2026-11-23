import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupApprovalTests, signIn } from "../../../test/approvalsKit";
import { decisionEl } from "../../../test/panel";

// Телефон (390 px): списки — карточками; форма решения лежит в центре карточки, окно открывать не нужно (ЕД-7).
setupApprovalTests(390);

describe("КП и согласования на телефоне", () => {
  it("форма одобрения — в центре карточки, без листа и без открытия окна", async () => {
    signIn("director@demo.example");
    renderAt(`/eds/drafts/${encodeURIComponent("КП-2026/116")}`);

    const center = await decisionEl();
    expect(await within(center).findByRole("form", { name: "Одобрение КП" })).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("старая ссылка из очереди ?panel=open&tab=approve ведёт к форме в центре и снимает параметры окна", async () => {
    signIn("director@demo.example");
    const { router } = renderAt(
      `/eds/drafts/${encodeURIComponent("КП-2026/116")}?panel=open&tab=approve`,
    );

    const center = await decisionEl();
    expect(await within(center).findByRole("form", { name: "Одобрение КП" })).toBeVisible();
    await waitFor(() => {
      expect(router.state.location.search).toBe("");
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  it("менеджер на телефоне: кнопки «Одобрить КП» на карточке нет", async () => {
    signIn("manager@demo.example");
    renderAt(`/eds/drafts/${encodeURIComponent("КП-2026/115")}`);

    expect(await screen.findByRole("heading", { level: 1, name: "КП-2026/115" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Одобрить КП$/ })).toBeNull();
  });
});
