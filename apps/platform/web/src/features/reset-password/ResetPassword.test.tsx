import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { readAudit } from "../../mocks/fixtures/audit";
import { endSession } from "../../mocks/mockSession";
import i18n from "../../shared/i18n";
import { panelEl } from "../../test/panel";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

async function openCard(id: string) {
  renderApp(`/admin/org?employee=${id}&panel=open`);
  const side = await panelEl();
  await within(side).findByRole("heading", { level: 3 });
  return side;
}

describe("Сброс пароля сотрудника по почте (карточка в Оргструктуре)", () => {
  it("«Что произойдёт», отправка, запись в журнале", async () => {
    signInAs("admin@demo.example");
    const side = await openCard("u-demo-manager");

    fireEvent.click(within(side).getByRole("button", { name: "Сбросить пароль" }));

    const group = within(side).getByRole("group", { name: "Сброс пароля" });
    expect(within(group).getByText("Что произойдёт")).toBeVisible();
    expect(
      within(group).getByText(/Сотрудник получит письмо на manager@demo\.example/),
    ).toBeVisible();
    expect(
      within(group).getByText(/Все его сессии в Платформе, CRM и ERP завершатся/),
    ).toBeVisible();
    expect(within(group).getByRole("radio", { name: "По почте" })).toBeChecked();
    expect(within(group).getByRole("radio", { name: "Временным паролем" })).toBeEnabled();

    fireEvent.click(within(group).getByRole("button", { name: "Сбросить и отправить письмо" }));

    expect(
      await screen.findByText("Письмо с новым паролем отправлено на manager@demo.example"),
    ).toBeVisible();
    await waitFor(() => {
      expect(within(side).queryByRole("group", { name: "Сброс пароля" })).toBeNull();
    });
    expect(readAudit()[0]).toMatchObject({
      action: "user.reset_password_email",
      entity_id: "u-demo-manager",
      actor_name: "Демо Админов",
    });
  });

  it("временным паролем: другие «Что произойдёт», пароль один раз, запись в журнале, пароль не в кэше", async () => {
    signInAs("admin@demo.example");
    const { queryClient } = renderApp("/admin/org?employee=u-demo-manager&panel=open");
    const side = await panelEl();
    await within(side).findByRole("heading", { level: 3, name: "Демо Менеджеров" });

    fireEvent.click(within(side).getByRole("button", { name: "Сбросить пароль" }));
    fireEvent.click(within(side).getByRole("radio", { name: "Временным паролем" }));

    const group = within(side).getByRole("group", { name: "Сброс пароля" });
    expect(within(group).getByText(/Прежний пароль перестанет действовать/)).toBeVisible();
    expect(within(group).queryByText(/получит письмо/)).toBeNull();

    fireEvent.click(within(group).getByRole("button", { name: "Выдать пароль" }));

    const input = await within(side).findByLabelText<HTMLInputElement>("Временный пароль");
    expect(input.value).toMatch(/^Tmp-/);
    expect(readAudit()[0]).toMatchObject({
      action: "user.reset_password",
      entity_id: "u-demo-manager",
      actor_name: "Демо Админов",
    });
    expect(
      JSON.stringify(
        queryClient
          .getMutationCache()
          .getAll()
          .map((m) => m.state),
      ),
    ).not.toContain(input.value);
    fireEvent.click(within(side).getByRole("button", { name: "Готово: пароль передан" }));
    await waitFor(() => {
      expect(within(side).queryByLabelText("Временный пароль")).toBeNull();
    });
    expect(within(side).getByRole("button", { name: "Сбросить пароль" })).toBeVisible();
  });

  it("отказ при выдаче временного пароля — ошибка словами, пароля нет", async () => {
    server.use(
      http.post("*/admin/users/:id/temporary-password", () =>
        HttpResponse.json({ code: "FORBIDDEN", message: "x", source: "crm" }, { status: 403 }),
      ),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/org?employee=u-demo-manager&panel=open");
    const side = await panelEl();
    await within(side).findByRole("heading", { level: 3, name: "Демо Менеджеров" });
    fireEvent.click(within(side).getByRole("button", { name: "Сбросить пароль" }));
    fireEvent.click(within(side).getByRole("radio", { name: "Временным паролем" }));

    fireEvent.click(within(side).getByRole("button", { name: "Выдать пароль" }));

    expect(await within(side).findByRole("alert")).toBeVisible();
    expect(within(side).queryByLabelText("Временный пароль")).toBeNull();
  });

  it("себе сбросить нельзя: кнопка недоступна, причина словами", async () => {
    signInAs("admin@demo.example");
    const side = await openCard("u-demo-admin");

    const button = within(side).getByRole("button", { name: "Сбросить пароль" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(/Свой пароль здесь не сбросить/);
  });

  it("ответ 409 self_reset от BFF показывается словами", async () => {
    server.use(
      http.post("*/admin/users/:id/reset-password/email", () =>
        HttpResponse.json(
          { code: "CONFLICT", message: "x", source: "bff", details: { reason: "self_reset" } },
          { status: 409 },
        ),
      ),
    );
    signInAs("admin@demo.example");
    const side = await openCard("u-demo-manager");
    fireEvent.click(within(side).getByRole("button", { name: "Сбросить пароль" }));
    fireEvent.click(within(side).getByRole("button", { name: "Сбросить и отправить письмо" }));

    expect(await within(side).findByRole("alert")).toHaveTextContent(
      "Свой пароль здесь не сбросить",
    );
  });

  it("почта не подключена: пароль не изменён, ссылка на Admin · Интеграции", async () => {
    server.use(
      http.post("*/admin/users/:id/reset-password/email", () =>
        HttpResponse.json(
          {
            code: "NOT_CONFIGURED",
            message: "x",
            source: "crm",
            details: { reason: "smtp_not_configured" },
          },
          { status: 409 },
        ),
      ),
    );
    signInAs("admin@demo.example");
    const side = await openCard("u-demo-manager");
    fireEvent.click(within(side).getByRole("button", { name: "Сбросить пароль" }));
    fireEvent.click(within(side).getByRole("button", { name: "Сбросить и отправить письмо" }));

    const alert = await within(side).findByRole("alert");
    expect(alert).toHaveTextContent("Почта не подключена, пароль не изменён");
    expect(within(alert).getByRole("link", { name: "Открыть Admin · Интеграции" })).toHaveAttribute(
      "href",
      "/admin/integrations",
    );
  });

  it("«Отмена» закрывает подтверждение, письмо не уходит", async () => {
    let calls = 0;
    server.use(
      http.post("*/admin/users/:id/reset-password/email", () => {
        calls += 1;
        return HttpResponse.json({ email_log_id: 1, status: "queued", to_email: "x@demo.example" });
      }),
    );
    signInAs("admin@demo.example");
    const side = await openCard("u-demo-manager");
    fireEvent.click(within(side).getByRole("button", { name: "Сбросить пароль" }));

    fireEvent.click(within(side).getByRole("button", { name: "Отмена" }));

    expect(within(side).getByRole("button", { name: "Сбросить пароль" })).toBeVisible();
    expect(calls).toBe(0);
  });

  it("директору кнопки нет: карточка только для чтения", async () => {
    signInAs("director@demo.example");
    const side = await openCard("u-demo-manager");

    expect(within(side).queryByRole("button", { name: "Сбросить пароль" })).toBeNull();
  });

  it("у отключённого сотрудника кнопки нет", async () => {
    signInAs("admin@demo.example");
    const side = await openCard("u-demo-disabled");

    expect(within(side).queryByRole("button", { name: "Сбросить пароль" })).toBeNull();
  });
});
