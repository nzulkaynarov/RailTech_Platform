import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resetEmployees } from "../../mocks/fixtures/employees";
import { resetRoles } from "../../mocks/fixtures/roles";
import { endSession } from "../../mocks/mockSession";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { setViewportWidth } from "../../test/viewport";
import { findMissing } from "./model";
import type { EmployeeCapabilities } from "../../shared/api/generated/model";

// ДОСТ-1: «Кто что может», карточка человека, «Мои возможности», «Нет возможности». Только чтение, MSW.
beforeEach(() => {
  window.localStorage.clear();
  resetEmployees();
  resetRoles();
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  cleanup();
  endSession();
});

describe("Кто что может", () => {
  it("«Кто что может» — пять областей сделки в строках, уровни, подпись и «отвечает за»; область раскрывается", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org?view=matrix");

    const table = await screen.findByRole("table", { name: "Что может каждый сотрудник" });
    expect(screen.getByRole("heading", { level: 1, name: "Сотрудники" })).toBeVisible();
    for (const area of [
      "Лиды и клиенты",
      "Заявки и расчёт",
      "КП и договор",
      "Оплата и документы",
      "Настройки",
    ]) {
      expect(within(table).getByRole("button", { name: new RegExp(area) })).toBeVisible();
    }
    // возможности свёрнуты: «Оплаты» видно только после раскрытия области
    expect(within(table).queryByRole("rowheader", { name: "Оплаты" })).toBeNull();
    fireEvent.click(within(table).getByRole("button", { name: /Оплата и документы/ }));
    const payments = within(table)
      .getByRole("rowheader", { name: "Оплаты" })
      .closest('[role="row"]') as HTMLElement;
    expect(within(payments).getAllByText("Решать").length).toBeGreaterThan(0);
    expect(within(payments).getAllByText("Смотреть").length).toBeGreaterThan(0);
    // в строках «Подписывает» и «Отвечает за» — одно короткое значение, подробности в подсказке
    expect(within(table).getByText("Подписывает")).toBeVisible();
    expect(within(table).getByText("Отвечает за")).toBeVisible();
    expect(within(table).queryByRole("button", { name: "Решать" })).toBeNull();
  });

  it("страница открывается списком; «Кто что может» — вторая вкладка, имя в таблице открывает карточку", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org");
    expect(
      await screen.findByRole("link", { name: "Открыть карточку: Демо Менеджеров" }),
    ).toBeVisible();
    expect(screen.queryByRole("table", { name: "Что может каждый сотрудник" })).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: "Кто что может" }));
    fireEvent.click(await screen.findByRole("link", { name: "Открыть: Демо Менеджеров" }));
    const panel = await waitFor(() => {
      const el = document.getElementById("pf-context-panel");
      if (!el) throw new Error("окно ещё не появилось");
      return el;
    });
    expect(
      await within(panel).findByRole("heading", { level: 3, name: "Что может этот человек" }),
    ).toBeVisible();
  });

  it("директор видит таблицу без кнопки «Пригласить»", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/org?view=matrix");
    await screen.findByRole("table", { name: "Что может каждый сотрудник" });
    expect(screen.queryByRole("button", { name: "Пригласить сотрудника" })).toBeNull();
  });
});

describe("Что может этот человек", () => {
  it("боковое окно — короткий итог по областям и «Открыть»; страница человека — таблица, подпись, области, замещение", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org?employee=u-demo-manager&panel=open&view=list");

    const card = await screen.findByTestId("cap-card");
    const summary = within(card).getByTestId("cap-summary");
    // не больше четырёх строк, каждая не длиннее 90 знаков вместе с подписью
    const lines = [...summary.querySelectorAll("[data-line]")];
    expect(lines.length).toBeGreaterThan(0);
    expect(lines.length).toBeLessThanOrEqual(4);
    for (const line of lines) expect(line.textContent.length).toBeLessThanOrEqual(90);
    expect(within(card).queryByTestId("cap-rows")).toBeNull();
    expect(
      within(card).getByRole("button", { name: "Изменить через роли (до следующего шага)" }),
    ).toBeVisible();
    cleanup();
    endSession();

    signInAs("admin@demo.example");
    renderApp("/admin/org/u-demo-manager");
    const page = await screen.findByTestId("cap-page");
    const contract = (await within(page).findByTestId("cap-rows")).querySelector(
      '[data-capability="contract"]',
    ) as HTMLElement;
    expect(within(contract).getByText("Смотреть")).toBeVisible();
    fireEvent.click(within(contract).getByRole("button"));
    expect(
      within(contract).getByText("готовить договор по шаблону и отправлять клиенту"),
    ).toBeVisible();
    expect(contract.querySelectorAll(".pf-cap-action-off").length).toBeGreaterThan(0);
    expect(within(contract).getByText(/Из роли: Менеджер/)).toBeVisible();
    expect(within(page).getByTestId("cap-signing")).toBeVisible();
    expect(within(page).getByTestId("cap-zones")).toBeVisible();
    expect(within(page).getByTestId("cap-deputy")).toBeVisible();
  });

  it("у директора ссылки на выдачу ролей в окне нет: он читает, а не выдаёт", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/org?employee=u-demo-manager&panel=open&view=list");
    await screen.findByTestId("cap-card");
    expect(screen.queryByTestId("cap-change-link")).toBeNull();
  });
});

describe("Мои возможности", () => {
  it("профиль: те же данные про себя, только чтение", async () => {
    signInAs("manager@demo.example");
    renderApp("/me?part=capabilities");

    const mine = await screen.findByTestId("my-capabilities");
    expect(within(mine).queryByText("Что я делаю")).toBeNull();
    expect(within(mine).queryByText("Что я решаю")).toBeNull();
    const leads = mine.querySelector('[data-capability="leads"]') as HTMLElement;
    expect(within(leads).getByText("Работать")).toBeVisible();
    const staff = mine.querySelector('[data-capability="staff"]') as HTMLElement;
    expect(within(staff).getByText("Нет")).toBeVisible();
    // свои подпись и зоны читает любой сотрудник: у менеджера их нет — так и сказано, блоки не пропадают
    expect(within(mine).getByTestId("cap-signing")).toHaveTextContent("по доверенности");
    expect(within(mine).getByTestId("cap-zones")).toBeVisible();
    expect(within(mine).getByRole("button", { name: "Попросить возможность" })).toBeEnabled();
  });
});

describe("Нет возможности", () => {
  it("«Нет доступа» называет недостающую возможность, а «Попросить» несёт её название в обращении", async () => {
    signInAs("manager@demo.example");
    renderApp("/admin/org");

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "«Сотрудники и возможности» вам не выдано",
      }),
    ).toBeVisible();
    expect(screen.getByText(/Сейчас у вас — «Нет»/)).toBeVisible();
    // кто выдаёт: в демо-данных «Сотрудники и возможности — работать» держит администратор
    expect(screen.getByText(/Выдают возможности: .*Демо Админов/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Попросить возможность" }));
    expect(
      await screen.findByDisplayValue("Нужна возможность «Сотрудники и возможности»: смотреть."),
    ).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  });
});

describe("findMissing", () => {
  const data = {
    groups: [
      {
        key: "g",
        rows: [
          {
            key: "payments",
            name: { ru: "Оплаты", uz: "", en: "" },
            level: "view",
            levels: [
              {
                level: "view",
                actions: [{ key: "read", gates: ["eds.payments:read"], on: true }],
              },
              {
                level: "decide",
                actions: [{ key: "confirm", gates: ["eds.payments:full"], on: false }],
              },
            ],
          },
        ],
      },
    ],
  } as unknown as EmployeeCapabilities;

  it("чтение раздела — «смотреть», изменение — решающее действие с тем же условием", () => {
    expect(findMissing(data, ["eds.payments"], "read")?.needed).toBe("view");
    expect(findMissing(data, ["eds.payments"], "full")?.needed).toBe("decide");
    expect(findMissing(data, ["eds.payments"], "full")?.current).toBe("view");
  });

  it("раздела нет в каталоге — ничего не выдумываем", () => {
    expect(findMissing(data, ["nothing"], "read")).toBeNull();
  });
});
