import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { writeEmployees, readEmployees } from "../../../mocks/fixtures/employees";
import { ROLE_ID, readRoles } from "../../../mocks/fixtures/roles";
import { endSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
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

async function panelEl(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.getElementById("pf-context-panel");
    if (!element) throw new Error("боковое окно ещё не появилось");
    return element;
  });
}

const table = () => screen.getByRole("table", { name: /Матрица ролей/ });

describe("Admin · Ролевая матрица (R-2, ADR-0012)", () => {
  it("строки — разделы по модулям, столбцы — роли; «скрыто» словом для скринридера", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/roles");

    expect(await screen.findByRole("button", { name: /^Администратор/ })).toBeVisible();
    const [head] = within(table()).getAllByRole("row");
    const headers = within(head as HTMLElement)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual([
      "Модуль · раздел",
      "Администраторсистемная роль",
      "Директорсистемная роль",
      "Менеджер",
      "Снабженец",
      "Гл. инженер",
      "Бухгалтер",
    ]);
    const row = within(table()).getByRole("row", { name: /Сводка по компании/ });
    expect(within(row).getAllByText("Скрыто")).toHaveLength(4);
    expect(within(row).getAllByText("Полный доступ")).toHaveLength(1);
    expect(within(row).getAllByText("Только чтение")).toHaveLength(1);
  });

  it("системная роль — только чтение: ни полей выбора, ни кнопки «Сохранить роль»", async () => {
    signInAs("admin@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.DIRECTOR}&panel=open&tab=role`);

    expect(
      await within(await panelEl()).findByText(/изменить или удалить её нельзя/),
    ).toBeVisible();
    expect(within(table()).queryAllByRole("combobox")).toHaveLength(0);
    expect(within(await panelEl()).queryByRole("button", { name: "Сохранить роль" })).toBeNull();
  });

  it("создать роль с нуля: столбец новой роли, «Что произойдёт», роль сохраняется в данных", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/roles?role=new&panel=open&tab=role");
    const panel = await panelEl();
    await within(panel).findByRole("heading", { level: 3, name: "Новая роль" });

    fireEvent.change(within(panel).getByLabelText("Название"), {
      target: { value: "Менеджер и бухгалтер" },
    });
    fireEvent.change(
      within(table()).getByRole("combobox", {
        name: "Все сообщения, Все лиды, Каналы связи, База знаний — роль «Менеджер и бухгалтер»",
      }),
      { target: { value: "full" } },
    );
    fireEvent.click(
      within(table()).getByRole("checkbox", {
        name: "Только итоговые суммы расчёта (без себестоимости по строкам) — роль «Менеджер и бухгалтер» видит",
      }),
    );
    expect(within(panel).getByText("Роль открывает модули: CRM.")).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Создать роль" }));

    await waitFor(() => {
      expect(readRoles().find((r) => r.name === "Менеджер и бухгалтер")).toMatchObject({
        system: false,
        access: { "crm.leads": "full" },
        restricted_fields: ["totals_only"],
      });
    });
  });

  it("Admin «полный» в созданной роли — предупреждение про полного администратора CRM", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/roles?role=new&panel=open&tab=role");
    const panel = await panelEl();
    await within(panel).findByRole("heading", { level: 3, name: "Новая роль" });

    fireEvent.change(
      within(table()).getByRole("combobox", {
        name: "Роли, Оргструктура, Интеграции, Тикеты — роль «Новая роль»",
      }),
      { target: { value: "full" } },
    );

    expect(within(panel).getAllByText(/только системная роль «Администратор»/)[0]).toBeVisible();
  });

  it("роль с сотрудниками: удалить нельзя — причина и неактивная кнопка; без сотрудников — можно", async () => {
    signInAs("admin@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.SUPPLY}&panel=open&tab=role`);
    const panel = await panelEl();

    expect(
      await within(panel).findByText(/Удалить нельзя: роль выдана сотрудникам \(2\)/),
    ).toBeVisible();
    expect(within(panel).getByRole("button", { name: "Удалить роль" })).toBeDisabled();
  });

  it("удаление свободной роли — с подтверждением", async () => {
    writeEmployees(
      readEmployees().map((e) => ({
        ...e,
        role_ids: e.role_ids.filter((id) => id !== ROLE_ID.ENGINEER),
      })),
    );
    signInAs("admin@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.ENGINEER}&panel=open&tab=role`);
    const panel = await panelEl();

    fireEvent.click(await within(panel).findByRole("button", { name: "Удалить роль" }));
    fireEvent.click(within(panel).getByRole("button", { name: "Удалить" }));

    await waitFor(() => {
      expect(readRoles().some((r) => r.id === ROLE_ID.ENGINEER)).toBe(false);
    });
  });

  it("директор (Admin — чтение) матрицу не загружает: текст, что её ведёт администратор", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/roles");

    expect(await screen.findByText("Ролевую матрицу ведёт администратор")).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
