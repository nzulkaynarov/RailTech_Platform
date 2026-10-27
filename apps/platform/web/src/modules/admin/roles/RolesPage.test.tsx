import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { writeEmployees, readEmployees } from "../../../mocks/fixtures/employees";
import { ROLE_ID, readRoles, writeRoles } from "../../../mocks/fixtures/roles";
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
        name: "Ждут ответа, Лиды, Каналы связи, База знаний бота — роль «Менеджер и бухгалтер»",
      }),
      { target: { value: "full" } },
    );
    fireEvent.click(
      within(table()).getByRole("checkbox", {
        name: "Только итоговые суммы расчёта (без себестоимости по строкам) — роль «Менеджер и бухгалтер» видит",
      }),
    );
    expect(within(panel).getByText("Роль открывает модули: Клиенты.")).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Создать роль" }));

    await waitFor(() => {
      expect(readRoles().find((r) => r.name === "Менеджер и бухгалтер")).toMatchObject({
        system: false,
        access: { "crm.leads": "full" },
        restricted_fields: ["totals_only"],
      });
    });
  });

  it("Admin «полный» в созданной роли — предупреждение: не суперпользователь ERP и без лидов CRM", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/roles?role=new&panel=open&tab=role");
    const panel = await panelEl();
    await within(panel).findByRole("heading", { level: 3, name: "Новая роль" });

    fireEvent.change(
      within(table()).getByRole("combobox", {
        name: "Роли и права, Сотрудники, Подключения, Telegram-бот, Журнал, Обращения сотрудников — роль «Новая роль»",
      }),
      { target: { value: "full" } },
    );

    expect(
      within(panel).getAllByText(
        /не суперпользователя ERP: его даёт только системная роль «Администратор»/,
      )[0],
    ).toBeVisible();
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

  it("директор (Admin — чтение) видит матрицу только для чтения: без кнопок и полей выбора", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/roles");

    expect(await screen.findByRole("button", { name: /^Менеджер/ })).toBeVisible();
    expect(screen.queryByText("Ролевую матрицу ведёт администратор")).toBeNull();
    expect(screen.getByText("Только просмотр")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Создать роль" })).toBeNull();
    expect(within(table()).queryAllByRole("combobox")).toHaveLength(0);
    expect(within(table()).queryAllByRole("checkbox")).toHaveLength(0);
    // Права директора видны в его столбце: лиды — только чтение.
    const row = within(table()).getByRole("row", { name: /Ждут ответа, Лиды/ });
    expect(within(row).getAllByText("Только чтение").length).toBeGreaterThan(0);
  });

  it("директор: выбранная роль в боковом окне — без правки, удаления и ссылки «Назначить»", async () => {
    signInAs("director@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.MANAGER}&panel=open&tab=role`);
    const panel = await panelEl();

    expect(await within(panel).findByText(/Только просмотр: роль и её матрицу/)).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Сохранить роль" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Удалить роль" })).toBeNull();
    expect(within(panel).queryByText("Назначить роль сотруднику")).toBeNull();
    expect(within(panel).queryByLabelText("Название")).toBeNull();
  });

  it("директор: во вкладке «Сотрудники» ссылка «Открыть» (карточка для чтения), не «Изменить»", async () => {
    signInAs("director@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.ENGINEER}&panel=open&tab=employees`);
    const panel = await panelEl();

    const link = await within(panel).findByRole("link", {
      name: "Открыть карточку: Демо Инженеров",
    });
    expect(link).toHaveTextContent("Открыть");
    expect(link.getAttribute("href")).toMatch(/^\/admin\/org\?employee=/);
    expect(within(panel).queryByText("Изменить")).toBeNull();
    expect(within(panel).queryByRole("link", { name: /^Изменить роли/ })).toBeNull();
  });

  it("админ: во вкладке «Сотрудники» ссылка «Изменить» ведёт в карточку с выдачей ролей", async () => {
    signInAs("admin@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.ENGINEER}&panel=open&tab=employees`);
    const panel = await panelEl();

    const link = await within(panel).findByRole("link", { name: "Изменить роли: Демо Инженеров" });
    expect(link).toHaveTextContent("Изменить");
  });

  it("«Что произойдёт»: число и глагол согласованы («1 сотрудник потеряет»)", async () => {
    signInAs("admin@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.ACCOUNTANT}&panel=open&tab=role`);
    const panel = await panelEl();
    await within(panel).findByRole("button", { name: "Сохранить роль" });

    fireEvent.change(
      within(table()).getByRole("combobox", {
        name: "С клиентами (Telegram-бот, почта) — роль «Бухгалтер»",
      }),
      { target: { value: "" } },
    );

    expect(await within(panel).findByText(/^1 сотрудник потеряет: /)).toBeVisible();
  });

  it("плюральные формы предпросмотра в ru, uz, en", () => {
    const t = (lng: string, key: string, count: number) =>
      i18n.t(`modules:admin.roles.preview.${key}`, { lng, count, list: "X" });
    expect(t("ru", "lost", 1)).toBe("1 сотрудник потеряет: X.");
    expect(t("ru", "lost", 2)).toBe("2 сотрудника потеряют: X.");
    expect(t("ru", "lost", 5)).toBe("5 сотрудников потеряют: X.");
    expect(t("ru", "lost", 21)).toBe("21 сотрудник потеряет: X.");
    expect(t("ru", "gained", 1)).toBe("1 сотрудник получит: X.");
    expect(t("ru", "gained", 3)).toBe("3 сотрудника получат: X.");
    expect(t("ru", "gained", 11)).toBe("11 сотрудников получат: X.");
    expect(t("en", "lost", 1)).toBe("1 employee will lose: X.");
    expect(t("en", "gained", 2)).toBe("2 employees will gain: X.");
    expect(t("uz", "lost", 2)).toBe("2 xodim yo'qotadi: X.");
  });

  it("вкладки роли: «Роль», «Сотрудники» и «Журнал» (с W13-A6)", async () => {
    signInAs("admin@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.MANAGER}&panel=open&tab=role`);
    const panel = await panelEl();

    const tabs = await within(panel).findAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Роль", "Сотрудники", "Журнал"]);
  });

  it("роль изменена другим пользователем: «обновите страницу» и кнопка «Обновить» возвращает данные", async () => {
    signInAs("admin@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.MANAGER}&panel=open&tab=role`);
    const panel = await panelEl();
    fireEvent.change(await within(panel).findByLabelText("Название"), {
      target: { value: "Продажи" },
    });
    // Пока администратор редактировал, роль изменил другой: версия в данных выросла.
    writeRoles(
      readRoles().map((r) =>
        r.id === ROLE_ID.MANAGER ? { ...r, name: "Менеджер продаж", version: r.version + 1 } : r,
      ),
    );

    fireEvent.click(within(panel).getByRole("button", { name: "Сохранить роль" }));

    expect(
      await within(panel).findByText("Роль изменена другим пользователем — обновите страницу."),
    ).toBeVisible();
    expect(readRoles().find((r) => r.id === ROLE_ID.MANAGER)?.name).toBe("Менеджер продаж");
    fireEvent.click(within(panel).getByRole("button", { name: "Обновить" }));

    await waitFor(() => {
      expect(
        within(panel).queryByText("Роль изменена другим пользователем — обновите страницу."),
      ).toBeNull();
    });
    await waitFor(() => {
      expect(within(panel).getByLabelText("Название")).toHaveValue("Менеджер продаж");
    });
  });

  it("сохранение роли присылает прочитанную версию и поднимает её", async () => {
    signInAs("admin@demo.example");
    renderApp(`/admin/roles?role=${ROLE_ID.MANAGER}&panel=open&tab=role`);
    const panel = await panelEl();
    fireEvent.change(await within(panel).findByLabelText("Название"), {
      target: { value: "Продажи" },
    });

    fireEvent.click(within(panel).getByRole("button", { name: "Сохранить роль" }));

    await waitFor(() => {
      expect(readRoles().find((r) => r.id === ROLE_ID.MANAGER)).toMatchObject({
        name: "Продажи",
        version: 2,
      });
    });
  });
});
