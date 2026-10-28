import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";
import { renderAt, setupProjectTests, signIn } from "../../../test/projectsKit";

setupProjectTests();

async function table() {
  return screen.findByRole("table", { name: /Проекты: номер, клиент/ });
}

describe("Проекты: список", () => {
  it("строки с ПР-номером, клиентом, шагом, статусом для клиента, документами и ответственным", async () => {
    signIn("director@demo.example");
    renderAt("/eds/projects");

    const rows = within(await table()).getAllByRole("row");
    // шапка + пять проектов мока
    expect(rows).toHaveLength(6);
    const first = rows.find((r) => r.textContent.includes("ПР-2026-105"));
    expect(first).toBeDefined();
    const row = within(first as HTMLElement);
    expect(row.getByRole("link", { name: "ПР-2026-105" })).toBeVisible();
    expect(first).toHaveTextContent("АО «Демо-Транс»");
    expect(first).toHaveTextContent("Согласуйте редакцию договора");
    expect(first).toHaveTextContent("Договор");
    expect(first).toHaveTextContent("Проект");
    expect(first).toHaveTextContent("Демо Помощников");
    expect(row.getByRole("link", { name: "Открыть проект ПР-2026-105" })).toBeVisible();
  });

  it("проект без договора помечен проблемой; «С проблемами» оставляет только такие", async () => {
    signIn("accountant@demo.example");
    renderAt("/eds/projects");
    await table();

    fireEvent.click(screen.getByRole("checkbox", { name: "С проблемами" }));

    await waitFor(() => {
      const rows = within(screen.getByRole("table")).getAllByRole("row");
      expect(rows).toHaveLength(3); // шапка + 104 (нет договора) + 81 (отклонён)
    });
    const body = screen.getByRole("table");
    expect(body).toHaveTextContent("Проекта договора нет");
    expect(body).toHaveTextContent("Договор отклонён клиентом");
    expect(body).not.toHaveTextContent("ПР-2026-097");
  });

  it("фильтр «Мои» оставляет проекты, где сотрудник — менеджер", async () => {
    signIn("manager@demo.example");
    renderAt("/eds/projects");
    await table();

    fireEvent.click(screen.getByText("Мои"));

    await waitFor(() => {
      expect(screen.getByRole("table")).not.toHaveTextContent("ПР-2026-105");
    });
    expect(screen.getByRole("table")).toHaveTextContent("ПР-2026-104");
  });

  it("шаг «Выполнено» и поиск по ПР-номеру", async () => {
    signIn("director@demo.example");
    renderAt("/eds/projects?step=DONE");

    await waitFor(() => {
      expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);
    });
    expect(screen.getByRole("table")).toHaveTextContent("ПР-2026-072");

    renderAt("/eds/projects?q=ПР-2026-097");
    await waitFor(() => {
      expect(screen.getAllByRole("table").at(-1)).toHaveTextContent("ПР-2026-097");
    });
  });

  it("пустой список — слова и подсказка, с фильтрами — «сбросить»", async () => {
    server.use(
      http.get("*/eds/projects", () =>
        HttpResponse.json({ items: [], total: 0, offset: 0, limit: 25 }),
      ),
    );
    signIn("director@demo.example");
    renderAt("/eds/projects");
    expect(await screen.findByText("Проектов пока нет")).toBeVisible();
    expect(screen.getByText(/Проект появляется, когда клиент принимает КП/)).toBeVisible();
  });

  it("с фильтрами и пустой выдачей предлагает сбросить фильтры", async () => {
    server.use(
      http.get("*/eds/projects", () =>
        HttpResponse.json({ items: [], total: 0, offset: 0, limit: 25 }),
      ),
    );
    signIn("director@demo.example");
    renderAt("/eds/projects?problems=1");
    expect(await screen.findByText("По фильтрам проектов нет")).toBeVisible();
    expect(screen.getByRole("button", { name: "Сбросить фильтры" })).toBeVisible();
  });

  it("ERP не отвечает — слова и «Повторить», не пустая таблица", async () => {
    server.use(
      http.get("*/eds/projects", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "x", source: "erp" },
          { status: 503 },
        ),
      ),
    );
    signIn("director@demo.example");
    renderAt("/eds/projects");
    expect(await screen.findByText("ERP не отвечает")).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });

  it("админ без раздела — «Нет доступа»", async () => {
    signIn("admin@demo.example");
    renderAt("/eds/projects");
    expect(await screen.findByText(/Нет доступа/)).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
