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
  it("«Кто что может» — таблица: шаги сделки, уровни, подпись и «отвечает за»", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org?view=matrix");

    const table = await screen.findByRole("table", { name: "Что может каждый сотрудник" });
    expect(
      screen.getByRole("heading", { level: 1, name: "Сотрудники" }),
    ).toBeVisible();
    for (const group of [
      "Лиды и клиенты",
      "Заявки и расчёт",
      "КП и договор",
      "Оплата и документы",
    ]) {
      expect(within(table).getByRole("columnheader", { name: new RegExp(group) })).toBeVisible();
    }
    // у бухгалтера «Оплаты» — решать; у менеджера те же «Оплаты» — смотреть
    const payments = within(table)
      .getByRole("rowheader", { name: "Оплаты" })
      .closest('[role="row"]') as HTMLElement;
    expect(within(payments).getAllByText("Решать").length).toBeGreaterThan(0);
    expect(within(payments).getAllByText("Смотреть").length).toBeGreaterThan(0);
    expect(within(table).getByText("Подписывает")).toBeVisible();
    expect(within(table).getByText("Отвечает за")).toBeVisible();
    // только чтение: ни одной кнопки выдачи в таблице
    expect(within(table).queryByRole("button")).toBeNull();
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
  it("итог словами, строка раскрывается в действия «есть» и «нет», выдача — прежняя, ролями", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org?employee=u-demo-manager&panel=open&view=list");

    const card = await screen.findByTestId("cap-card");
    // пока нет сводки по областям, абзацев «Что делает / Что решает» нет; предупреждений в карточке нет
    expect(within(card).queryByText("Что делает")).toBeNull();
    expect(within(card).queryByText("Что решает")).toBeNull();
    expect(within(card).queryByTestId("cap-warnings")).toBeNull();
    const contract = card.querySelector('[data-capability="contract"]') as HTMLElement;
    expect(within(contract).getByText("Смотреть")).toBeVisible();
    fireEvent.click(within(contract).getByRole("button"));
    expect(
      within(contract).getByText("готовить договор по шаблону и отправлять клиенту"),
    ).toBeVisible();
    // у менеджера подготовка договора выключена, чтение — включено
    expect(contract.querySelectorAll(".pf-cap-action-off").length).toBeGreaterThan(0);
    expect(within(contract).getByText(/Из роли: Менеджер/)).toBeVisible();
    expect(within(card).getByTestId("cap-signing")).toBeVisible();
    expect(within(card).getByTestId("cap-zones")).toBeVisible();
    expect(within(card).getByTestId("cap-deputy")).toBeVisible();
    expect(
      within(card).getByRole("button", { name: "Изменить через роли (до следующего шага)" }),
    ).toBeVisible();
  });

  it("у директора ссылки на выдачу ролей нет: он читает, а не выдаёт", async () => {
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
