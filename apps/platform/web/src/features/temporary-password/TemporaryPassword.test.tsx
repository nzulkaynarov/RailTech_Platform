import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { resetEmployees } from "../../mocks/fixtures/employees";
import { resetRoles } from "../../mocks/fixtures/roles";
import { endSession } from "../../mocks/mockSession";
import { resetSetup } from "../../mocks/setupState";
import type { EmployeeInvite } from "../../shared/api/generated/model";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";

const written: string[] = [];

beforeEach(() => {
  window.localStorage.clear();
  resetSetup();
  resetEmployees();
  resetRoles();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
  written.length = 0;
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: vi.fn((text: string) => {
        written.push(text);
        return Promise.resolve();
      }),
    },
  });
});
afterEach(() => {
  endSession();
});

async function panel(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.getElementById("pf-context-panel");
    if (!element) throw new Error("боковое окно ещё не появилось");
    return element;
  });
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

/** Пароль виден только пока открыто окно с паролем: ни в тексте страницы, ни в адресе, ни в кэше мутаций. */
function expectGone(password: string, queryClient: { getMutationCache: () => unknown }) {
  expect(document.body).not.toHaveTextContent(password);
  for (const input of document.querySelectorAll("input")) expect(input.value).not.toBe(password);
  const cached = (
    queryClient.getMutationCache() as { getAll: () => { state: { data?: unknown } }[] }
  ).getAll();
  expect(JSON.stringify(cached.map((m) => m.state.data ?? null))).not.toContain(password);
}

describe("Приглашение без почты: временный пароль показывается один раз", () => {
  it("создание: пароль, предупреждение, «Копировать»; после «Готово» пароля нигде нет", async () => {
    const issued = `Tmp-${globalThis.crypto.randomUUID().replaceAll("-", "").slice(0, 14)}`;
    let sent: EmployeeInvite | undefined;
    server.use(
      http.post("*/admin/users", async ({ request }) => {
        sent = (await request.json()) as EmployeeInvite;
        return HttpResponse.json(
          {
            employee: {
              id: "u-new-1",
              name: sent.name,
              initials: "НС",
              email: sent.email,
              roles: [],
              access: { crm: true, erp: true },
              status: "invited",
              telegram_linked: false,
              erp_sync: "pending",
            },
            temporary_password: issued,
          },
          { status: 201, headers: { "Cache-Control": "no-store" } },
        );
      }),
    );
    signInAs("admin@demo.example");
    const { queryClient, router } = renderApp("/admin/org?invite=open&panel=open");
    const side = await panel();
    await within(side).findByRole("checkbox", { name: /^Снабженец/ });

    // способ передачи доступа; «Что произойдёт» про пароль, а не про письмо
    fireEvent.click(within(side).getByRole("radio", { name: "Временным паролем, без почты" }));
    fill("Имя и фамилия", "Новый Сотрудник");
    fill("Электронная почта", "no.mail@demo.example");
    fireEvent.click(within(side).getByRole("checkbox", { name: /^Снабженец/ }));
    expect(within(side).getByText(/Вы увидите временный пароль один раз/)).toBeVisible();
    expect(within(side).queryByText(/уйдёт письмо/)).toBeNull();

    fireEvent.click(within(side).getByRole("button", { name: "Создать и показать пароль" }));

    const input = await within(side).findByLabelText("Временный пароль");
    expect(input).toHaveValue(issued);
    expect(input).toHaveAttribute("readonly");
    expect(within(side).getByText(/Пароль показан один раз/)).toBeVisible();
    expect(sent).toEqual({
      email: "no.mail@demo.example",
      name: "Новый Сотрудник",
      role_ids: ["4"],
    });
    // в адресе и истории пароля нет
    expect(router.state.location.search).not.toContain(issued);
    // пока окно открыто, пароль есть только в поле; кэш мутаций его не хранит
    const cache = JSON.stringify(
      queryClient
        .getMutationCache()
        .getAll()
        .map((m) => m.state.data ?? null),
    );
    expect(cache).not.toContain(issued);

    fireEvent.click(within(side).getByRole("button", { name: "Копировать" }));
    expect(await within(side).findByText("Пароль скопирован")).toBeVisible();
    expect(written).toEqual([issued]);

    fireEvent.click(within(side).getByRole("button", { name: "Готово: пароль передан" }));

    await waitFor(() => {
      expect(screen.queryByLabelText("Временный пароль")).toBeNull();
    });
    expectGone(issued, queryClient);
    expect(router.state.location.search).not.toContain(issued);
    expect(router.state.location.search).toContain("employee=u-new-1");
  });

  it("почта уже есть — ошибка у поля, пароль не показан", async () => {
    server.use(
      http.post("*/admin/users", () =>
        HttpResponse.json({ code: "EMAIL_EXISTS", message: "x", source: "crm" }, { status: 409 }),
      ),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/org?invite=open&panel=open");
    const side = await panel();
    await within(side).findByRole("checkbox", { name: /^Снабженец/ });
    fireEvent.click(within(side).getByRole("radio", { name: "Временным паролем, без почты" }));
    fill("Имя и фамилия", "Новый Сотрудник");
    fill("Электронная почта", "dup@demo.example");
    fireEvent.click(within(side).getByRole("checkbox", { name: /^Снабженец/ }));

    fireEvent.click(within(side).getByRole("button", { name: "Создать и показать пароль" }));

    expect(await within(side).findByText("Сотрудник с такой почтой уже есть.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Временный пароль")).toBeNull();
  });

  it("если буфер недоступен — подсказка выделить пароль вручную", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: () => Promise.reject(new Error("denied")) },
    });
    signInAs("admin@demo.example");
    renderApp("/admin/org?employee=u-demo-invited&panel=open");
    const side = await panel();
    fireEvent.click(await within(side).findByRole("button", { name: "Выдать временный пароль" }));
    fireEvent.click(await within(side).findByRole("button", { name: "Выдать пароль" }));
    await within(side).findByLabelText("Временный пароль");

    fireEvent.click(within(side).getByRole("button", { name: "Копировать" }));

    expect(await within(side).findByText(/Не удалось скопировать/)).toBeVisible();
  });
});

describe("Карточка приглашённого: «Выдать временный пароль»", () => {
  it("подтверждение с «Что произойдёт», затем пароль один раз", async () => {
    signInAs("admin@demo.example");
    const { queryClient } = renderApp("/admin/org?employee=u-demo-invited&panel=open");
    const side = await panel();

    fireEvent.click(await within(side).findByRole("button", { name: "Выдать временный пароль" }));

    const group = await within(side).findByRole("group", { name: "Выдать временный пароль" });
    expect(within(group).getByText("Что произойдёт")).toBeVisible();
    expect(within(group).getByText(/Прежний пароль перестанет действовать/)).toBeVisible();

    fireEvent.click(within(group).getByRole("button", { name: "Выдать пароль" }));

    const input = await within(side).findByLabelText("Временный пароль");
    const password = (input as HTMLInputElement).value;
    expect(password).toMatch(/^Tmp-/);
    expect(within(side).getByText(/Сотрудник: Демо Приглашённая/)).toBeVisible();

    fireEvent.click(within(side).getByRole("button", { name: "Готово: пароль передан" }));
    await waitFor(() => {
      expect(screen.queryByLabelText("Временный пароль")).toBeNull();
    });
    expectGone(password, queryClient);
    // кнопка вернулась в исходное состояние; пароль повторно не получить — только выдать новый
    expect(within(side).getByRole("button", { name: "Выдать временный пароль" })).toBeVisible();
  });

  it("«Отмена» ничего не выдаёт", async () => {
    let calls = 0;
    server.use(
      http.post("*/admin/users/:id/temporary-password", () => {
        calls += 1;
        return HttpResponse.json({}, { status: 500 });
      }),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/org?employee=u-demo-invited&panel=open");
    const side = await panel();
    fireEvent.click(await within(side).findByRole("button", { name: "Выдать временный пароль" }));
    fireEvent.click(await within(side).findByRole("button", { name: "Отмена" }));

    expect(within(side).getByRole("button", { name: "Выдать временный пароль" })).toBeVisible();
    expect(calls).toBe(0);
  });

  it("отказ CRM — ошибка словами, пароля нет", async () => {
    server.use(
      http.post("*/admin/users/:id/temporary-password", () =>
        HttpResponse.json({ code: "FORBIDDEN", message: "x", source: "crm" }, { status: 403 }),
      ),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/org?employee=u-demo-invited&panel=open");
    const side = await panel();
    fireEvent.click(await within(side).findByRole("button", { name: "Выдать временный пароль" }));
    fireEvent.click(await within(side).findByRole("button", { name: "Выдать пароль" }));

    expect(await within(side).findByRole("alert")).toBeVisible();
    expect(screen.queryByLabelText("Временный пароль")).toBeNull();
  });

  it("у активного сотрудника кнопки нет (сброс пароля — отдельная задача)", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org?employee=u-demo-manager&panel=open");
    const side = await panel();
    await within(side).findByRole("heading", { level: 3, name: "Демо Менеджеров" });

    expect(within(side).queryByRole("button", { name: "Выдать временный пароль" })).toBeNull();
  });

  it("директор (admin: чтение) не видит ни кнопки, ни способа «без почты»", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/org?employee=u-demo-invited&panel=open");
    const side = await panel();
    await within(side).findByRole("heading", { level: 3, name: "Демо Приглашённая" });

    expect(within(side).queryByRole("button", { name: "Выдать временный пароль" })).toBeNull();
    expect(screen.queryByRole("radio", { name: "Временным паролем, без почты" })).toBeNull();
  });
});
