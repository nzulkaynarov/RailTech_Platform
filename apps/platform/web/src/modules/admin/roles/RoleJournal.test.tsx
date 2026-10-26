import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { endSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { panelEl } from "../../../test/panel";
import { renderApp, signInAs } from "../../../test/renderApp";
import { ROLE_ID } from "../../../test/roles";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

async function openJournal(email: string, roleId: string) {
  signInAs(email);
  renderApp(`/admin/roles?role=${roleId}&panel=open&tab=journal`);
  const side = await panelEl();
  return side;
}

describe("Ролевая матрица · вкладка «Журнал»", () => {
  it("у роли с историей: кто, когда и что изменилось — новые первыми", async () => {
    const side = await openJournal("admin@demo.example", ROLE_ID.MANAGER);

    expect(
      await within(side).findByRole("heading", { level: 3, name: "Журнал роли «Менеджер»" }),
    ).toBeVisible();
    const list = await within(side).findByRole("list", { name: "Изменения роли" });
    const text = list.textContent;
    expect(text.indexOf("Изменена роль")).toBeLessThan(text.indexOf("Создана роль «Менеджер»"));
    expect(within(side).getByText(/24\.10\.2026 21:48 · Демо Админов/)).toBeVisible();
    expect(
      within(side).getByText(/ERP · Все запросы, Расчёт: Скрыто → Только чтение/),
    ).toBeVisible();
    expect(within(side).getByText(/Поле «Цены поставщиков»: станет видно/)).toBeVisible();
  });

  it("сохранение роли добавляет запись в журнал", async () => {
    signInAs("admin@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.MANAGER}&panel=open&tab=role`);
    const side = await panelEl();
    fireEvent.change(await within(side).findByLabelText("Название"), {
      target: { value: "Продажи" },
    });
    fireEvent.click(within(side).getByRole("button", { name: "Сохранить роль" }));
    await screen.findByText("Роль сохранена");

    fireEvent.click(within(side).getByRole("tab", { name: "Журнал" }));

    expect(await within(side).findByText("Название: «Менеджер» → «Продажи»")).toBeVisible();
  });

  it("системная роль: изменений не было — пустое состояние словами", async () => {
    const side = await openJournal("admin@demo.example", ROLE_ID.ADMIN);

    expect(await within(side).findByText("Изменений пока не было")).toBeVisible();
  });

  it("директор читает журнал роли", async () => {
    const side = await openJournal("director@demo.example", ROLE_ID.MANAGER);

    expect(await within(side).findByText("Создана роль «Менеджер»")).toBeVisible();
  });

  it("роль не выбрана — подсказка вкладки", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/roles?panel=open&tab=journal");

    expect(await within(await panelEl()).findByText("Запись не выбрана")).toBeVisible();
  });

  it("ошибка CRM — слова и «Повторить»", async () => {
    server.use(
      http.get("*/admin/roles/:id/journal", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "x", source: "crm" },
          { status: 503 },
        ),
      ),
    );
    const side = await openJournal("admin@demo.example", ROLE_ID.MANAGER);

    expect(await within(side).findByText("Не удалось загрузить журнал роли")).toBeVisible();
    await waitFor(() => {
      expect(within(side).getByRole("button", { name: "Повторить" })).toBeVisible();
    });
  });
});
