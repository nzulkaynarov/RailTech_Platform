import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";

// Телефон (390 px): список — карточками, «Резолюция» — лист на весь экран с кнопками внизу (UX-оценка P0-4).
setupLetterTests(390);

async function sheet(): Promise<HTMLElement> {
  return screen.findByRole("dialog", { name: /^Резолюция/ });
}

describe("Входящие письма на телефоне", () => {
  it("список — карточки; строка открывает лист «Резолюция» на весь экран, а не окно каркаса", async () => {
    signIn("director@demo.example");
    const { router } = renderAt("/eds/inbox");
    expect(await screen.findByRole("list", { name: "Входящие письма" })).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: "Показать письмо ВХ-104/26 в боковом окне" }));

    const dialog = await sheet();
    expect(router.state.location.search).toContain("sheet=resolution");
    expect(router.state.location.search).not.toContain("panel=open");
    expect(await within(dialog).findByRole("form", { name: "Резолюция директора" })).toBeVisible();
    expect(
      within(dialog).getByRole("button", { name: "Утвердить резолюцию → задание в расчёт" }),
    ).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Вернуть менеджеру" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Отклонить" })).toBeVisible();
    // лист на всю высоту; кнопки решения закреплены внизу
    expect(dialog.closest(".ant-drawer-bottom")).not.toBeNull();
    expect(within(dialog).getByRole("form").querySelector(".pf-res-actions")).not.toBeNull();
  });

  it("ссылка из очереди с panel=open на телефоне превращается в лист", async () => {
    signIn("director@demo.example");
    const { router } = renderAt("/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution");

    const dialog = await sheet();
    expect(await within(dialog).findByRole("form", { name: "Резолюция директора" })).toBeVisible();
    expect(router.state.location.search).toContain("sheet=resolution");
    expect(router.state.location.search).not.toContain("panel=open");
  });

  it("карточка: кнопка «Наложить резолюцию» открывает лист, «Закрыть» — закрывает", async () => {
    signIn("director@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-104%2F26");

    fireEvent.click(await screen.findByRole("button", { name: "Наложить резолюцию" }));
    const dialog = await sheet();
    expect(within(dialog).getByText("Резолюция на письмо ВХ-104/26")).toBeVisible();

    fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть" }));
    await screen.findByRole("heading", { level: 1, name: "Письмо ВХ-104/26" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("менеджер на телефоне: кнопки «Наложить резолюцию» нет", async () => {
    signIn("manager@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-104%2F26");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Письмо ВХ-104/26" }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Наложить резолюцию" })).toBeNull();
  });
});
