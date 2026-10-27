import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { endSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { panelEl } from "../../../test/panel";
import { renderApp, signInAs } from "../../../test/renderApp";
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

describe("Admin · Журнал аудита (экран целиком на MSW)", () => {
  it("админ видит записи новыми первыми, входы скрыты; пункт есть в меню Admin", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/audit");

    expect(
      await screen.findByRole("heading", { level: 1, name: "История действий" }),
    ).toBeVisible();
    const table = await screen.findByRole("table", { name: "Записи журнала аудита" });
    const rows = within(table).getAllByRole("row");
    // заголовок + 13 записей без двух входов (15 всего)
    expect(rows).toHaveLength(14);
    expect(
      within(rows[1] as HTMLElement).getByText("Сбросил пароль и отправил по почте"),
    ).toBeVisible();
    expect(within(table).queryByText("Вход")).toBeNull();
    expect(screen.getByText("Записей: 13")).toBeVisible();
    expect(screen.getByRole("link", { name: /История действий/ })).toBeVisible();
  });

  it("«Показывать входы в систему» добавляет входы", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/audit");
    await screen.findByRole("table", { name: "Записи журнала аудита" });

    fireEvent.click(screen.getByRole("switch", { name: "Показывать входы в систему" }));

    await waitFor(() => {
      expect(screen.getByText("Записей: 15")).toBeVisible();
    });
    expect(screen.getAllByText("Вход").length).toBeGreaterThan(0);
  });

  it("фильтры: по объекту и автору; ничего не найдено — слова и «Сбросить фильтры»", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/audit?entity_type=platform_role");

    await waitFor(() => {
      expect(screen.getByText("Записей: 2")).toBeVisible();
    });
    fireEvent.change(screen.getByLabelText("С даты"), { target: { value: "2026-10-24" } });
    await waitFor(() => {
      expect(screen.getByText("Записей: 1")).toBeVisible();
    });
    fireEvent.change(screen.getByLabelText("С даты"), { target: { value: "2026-12-01" } });
    expect(await screen.findByText("По этим фильтрам записей нет")).toBeVisible();

    fireEvent.click(screen.getAllByRole("button", { name: "Сбросить фильтры" })[0] as HTMLElement);
    await waitFor(() => {
      expect(screen.getByText("Записей: 13")).toBeVisible();
    });
  });

  it("запись открывается в боковом окне: кто, когда, что изменилось (до → после)", async () => {
    signInAs("admin@demo.example");
    const { router } = renderApp("/admin/audit");

    fireEvent.click(
      await screen.findByRole("link", { name: /Открыть запись: Изменил сотрудника, 25\.10\.2026/ }),
    );

    const side = await panelEl();
    expect(
      await within(side).findByRole("heading", { level: 3, name: "Изменил сотрудника" }),
    ).toBeVisible();
    expect(router.state.location.search).toContain("entry=118");
    expect(within(side).getByText("Роли Платформы")).toBeVisible();
    expect(within(side).getByText("Менеджер, Снабженец")).toBeVisible();
    expect(
      within(side).getByRole("link", { name: "Открыть: Сотрудник: Демо Менеджеров" }),
    ).toBeVisible();
  });

  it("запись об изменении роли показывает изменённые разделы словами", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/audit?entry=116&panel=open");

    const side = await panelEl();
    expect(
      await within(side).findByText(
        /Расчёт · Заявки в расчёте, Мои расчёты: Скрыто → Только чтение/,
      ),
    ).toBeVisible();
    expect(within(side).getByText(/Поле «Цены поставщиков»: станет видно/)).toBeVisible();
  });

  it("секретные значения не показываются, запись без «до/после» объясняет это", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/audit?entry=120&panel=open");

    expect(
      await within(await panelEl()).findByText(
        "Для этого действия значения «до» и «после» не записываются.",
      ),
    ).toBeVisible();
  });

  it("директор читает журнал", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/audit");

    expect(await screen.findByRole("table", { name: "Записи журнала аудита" })).toBeVisible();
  });

  it("без раздела Admin — «Нет доступа», пункта в меню нет", async () => {
    signInAs("manager@demo.example");
    renderApp("/admin/audit");

    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "История действий" })).toBeNull();
  });

  it("постранично: 50 записей на странице и переход на вторую", async () => {
    let offsets: number[] = [];
    server.use(
      http.get("*/admin/audit", ({ request }) => {
        const q = new URL(request.url).searchParams;
        const offset = Number(q.get("offset") ?? 0);
        offsets = [...offsets, offset];
        const at = "2026-10-26T09:00:00Z";
        const count = offset === 0 ? 50 : 20;
        const items = Array.from({ length: count }, (_, i) => ({
          id: String(1000 - offset - i),
          at,
          actor_type: "user",
          actor_name: "Демо Админов",
          action: "settings.update",
          entity_type: "settings",
        }));
        return HttpResponse.json({ items, total: 70, limit: 50, offset });
      }),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/audit");
    await screen.findByText("Записей: 70");

    fireEvent.click(screen.getByRole("listitem", { name: "2" }));

    await waitFor(() => {
      expect(offsets).toContain(50);
    });
    expect(await screen.findAllByRole("row")).toHaveLength(21);
  });

  it("ошибка CRM — слова и «Повторить»", async () => {
    server.use(
      http.get("*/admin/audit", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "x", source: "crm" },
          { status: 503 },
        ),
      ),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/audit");

    expect(await screen.findByText("Не удалось загрузить журнал")).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });

  it("пустой журнал — пустое состояние словами", async () => {
    server.use(
      http.get("*/admin/audit", () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/audit");

    expect(await screen.findByText("Записей пока нет")).toBeVisible();
  });

  it("на узком экране записи — списком", async () => {
    setViewportWidth(390);
    signInAs("admin@demo.example");
    renderApp("/admin/audit");

    expect(await screen.findByRole("list", { name: "Записи журнала аудита" })).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
