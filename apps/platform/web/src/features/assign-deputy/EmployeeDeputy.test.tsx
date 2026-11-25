import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AppProviders } from "../../app/providers";
import { createQueryClient } from "../../app/queryClient";
import { routes } from "../../app/router";
import { usePanelsStore } from "../../app/shell/panelsStore";
import { readAudit } from "../../mocks/fixtures/audit";
import { findUser } from "../../mocks/fixtures/users";
import { endSession, startSession } from "../../mocks/mockSession";
import { readProfile, todayIso } from "../../mocks/profileStore";
import i18n from "../../shared/i18n";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";

/** СОТР-1: Telegram в трёх состояниях и замещение за сотрудника в карточке администратора (экран целиком на MSW). */

function renderAt(path: string) {
  const queryClient = createQueryClient({ retry: false, staleTime: 0 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

function signIn(email: string) {
  const user = findUser(email);
  if (!user) throw new Error(`нет демо-пользователя ${email}`);
  startSession(user);
}

async function panelEl(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.getElementById("pf-context-panel");
    if (!element) throw new Error("боковое окно ещё не появилось");
    return element;
  });
}

async function option(label: string): Promise<Element> {
  return waitFor(() => {
    const found = document.querySelector(`.ant-select-item-option[title^="${label}"]`);
    expect(found).not.toBeNull();
    return found as Element;
  });
}

function pickDate(label: string, value: string) {
  const input = screen.getByLabelText(label);
  fireEvent.mouseDown(input);
  fireEvent.change(input, { target: { value } });
  fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 13, charCode: 13 });
  fireEvent.blur(input);
}

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

describe("Карточка сотрудника · Telegram", () => {
  it("в списке три состояния: привязан, не привязан, сообщения не доходят", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org");

    const linked = await screen.findByRole("row", { name: /Демо Менеджеров/ });
    expect(within(linked).getByText("Telegram")).toBeVisible();
    expect(
      within(screen.getByRole("row", { name: /Демо Снабженцев/ })).getByText("Telegram: нет"),
    ).toBeVisible();
    expect(
      within(screen.getByRole("row", { name: /Демо Бухгалтеров/ })).getByText(
        "Telegram: не доходит",
      ),
    ).toBeVisible();
  });

  it("в карточке — слова: у «не доходит» сказано, что сделать", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?employee=u-demo-accountant&panel=open");

    const panel = await panelEl();
    expect(await within(panel).findByText(/сообщения не доходят/)).toBeVisible();
  });
});

describe("Карточка сотрудника · Замещение", () => {
  it("администратор назначает и снимает замещение за сотрудника; в журнале обе записи", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?employee=u-demo-supply&panel=open");

    const deputy = await within(await panelEl()).findByTestId("employee-deputy");
    expect(within(deputy).getByText("Замещение не назначено.")).toBeVisible();
    const select = within(deputy).getByRole("combobox", { name: "Кто замещает" });
    fireEvent.mouseDown(select);
    // сам сотрудник в списке заместителей не предлагается
    await option("Демо Директоров");
    expect(document.querySelector('.ant-select-item-option[title^="Демо Снабженцев"]')).toBeNull();
    fireEvent.click(await option("Демо Директоров"));
    const year = new Date().getFullYear() + 1;
    pickDate("С даты", `01.12.${String(year)}`);
    pickDate("По дату", `10.12.${String(year)}`);
    fireEvent.click(within(deputy).getByRole("button", { name: /Назначить$/ }));

    await waitFor(() => {
      expect(within(deputy).getByTestId("employee-deputy-sentence")).toHaveTextContent(
        `Демо Директоров с 01.12.${String(year)} по 10.12.${String(year)}`,
      );
    });
    expect(readProfile("u-demo-supply").deputy?.id).toBe("u-demo-director");
    expect(readAudit().some((e) => e.action === "user.deputy_set")).toBe(true);

    fireEvent.click(within(deputy).getByRole("button", { name: /Снять замещение$/ }));
    expect(await within(deputy).findByText("Замещение не назначено.")).toBeVisible();
    expect(readProfile("u-demo-supply").deputy).toBeUndefined();
    expect(readAudit().some((e) => e.action === "user.deputy_cleared")).toBe(true);
  }, 20_000);

  it("неполная форма не уходит: сказано, что выбрать", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?employee=u-demo-supply&panel=open");

    const deputy = await within(await panelEl()).findByTestId("employee-deputy");
    fireEvent.mouseDown(within(deputy).getByRole("combobox", { name: "Кто замещает" }));
    fireEvent.click(await option("Демо Директоров"));
    fireEvent.click(await within(deputy).findByRole("button", { name: /Назначить$/ }));

    expect(await within(deputy).findByRole("alert")).toHaveTextContent(
      "Выберите коллегу и обе даты",
    );
    expect(readProfile("u-demo-supply").deputy).toBeUndefined();
  }, 15_000);

  it("отказ CRM по подкоду — словами карточки", async () => {
    server.use(
      http.patch("*/admin/users/:id", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "x",
            source: "crm",
            details: { reason: "deputy_is_self" },
          },
          { status: 422 },
        ),
      ),
    );
    signIn("admin@demo.example");
    renderAt("/admin/org?employee=u-demo-supply&panel=open");

    const deputy = await within(await panelEl()).findByTestId("employee-deputy");
    fireEvent.mouseDown(within(deputy).getByRole("combobox", { name: "Кто замещает" }));
    fireEvent.click(await option("Демо Директоров"));
    const year = new Date().getFullYear() + 1;
    pickDate("С даты", `01.12.${String(year)}`);
    pickDate("По дату", `10.12.${String(year)}`);
    fireEvent.click(within(deputy).getByRole("button", { name: /Назначить$/ }));

    expect(await within(deputy).findByRole("alert")).toHaveTextContent(
      "Заместителем нельзя назначить самого сотрудника.",
    );
  }, 15_000);

  it("замещение, которое поставил сам сотрудник, видно администратору с именем", async () => {
    signIn("admin@demo.example");
    // как после «Профиль · Замещение»
    const { patchProfile } = await import("../../mocks/profileStore");
    patchProfile("u-demo-supply", {
      deputy: { id: "u-demo-director", date_from: todayIso(), date_to: todayIso() },
    });
    renderAt("/admin/org?employee=u-demo-supply&panel=open");

    const deputy = await within(await panelEl()).findByTestId("employee-deputy");
    expect(await within(deputy).findByTestId("employee-deputy-sentence")).toHaveTextContent(
      "Демо Директоров",
    );
  });

  it("директор читает: формы замещения нет, замещение — строкой", async () => {
    const { patchProfile } = await import("../../mocks/profileStore");
    patchProfile("u-demo-supply", {
      deputy: { id: "u-demo-director", date_from: todayIso(), date_to: todayIso() },
    });
    signIn("director@demo.example");
    renderAt("/admin/org?employee=u-demo-supply&panel=open");

    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { level: 3, name: "Демо Снабженцев" }),
    ).toBeVisible();
    expect(within(panel).queryByTestId("employee-deputy")).toBeNull();
    expect(within(panel).getByText("Демо Директоров", { exact: false })).toBeVisible();
  });
});
