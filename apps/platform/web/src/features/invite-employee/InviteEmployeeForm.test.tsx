import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Employee, EmployeeInvite } from "../../shared/api/generated/model";
import { ROLE_ID, ref, rolesHandler } from "../../test/roles";
import { server } from "../../test/server";
import { renderUi } from "../../test/renderUi";
import { InviteEmployeeForm } from "./InviteEmployeeForm";

const created: Employee = {
  id: "101",
  name: "Новый Сотрудник",
  initials: "НС",
  email: "new@demo.example",
  roles: [ref("SUPPLY")],
  access: { crm: true, erp: true },
  status: "invited",
  telegram_linked: false,
  erp_sync: "ok",
};

let bodies: EmployeeInvite[] = [];
const onInvited = vi.fn();
const onOpenCard = vi.fn();
const onCancel = vi.fn();

beforeEach(() => {
  bodies = [];
  onInvited.mockReset();
  onOpenCard.mockReset();
  onCancel.mockReset();
  server.use(
    rolesHandler(),
    http.post("*/admin/users/invite", async ({ request }) => {
      bodies.push((await request.json()) as EmployeeInvite);
      return HttpResponse.json(created, { status: 201 });
    }),
  );
});

/** Форма и роли компании (`GET /admin/roles`): флажки появляются после загрузки списка. */
async function setup() {
  renderUi(
    <InviteEmployeeForm onInvited={onInvited} onOpenCard={onOpenCard} onCancel={onCancel} />,
  );
  await screen.findByRole("checkbox", { name: /^Менеджер/ });
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

const submit = () => fireEvent.click(screen.getByRole("button", { name: "Отправить приглашение" }));

describe("InviteEmployeeForm: приглашение по почте", () => {
  it("пустая форма: тексты у полей и у ролей, запрос не уходит", async () => {
    await setup();

    submit();

    expect(await screen.findByText("Укажите имя и фамилию")).toBeInTheDocument();
    expect(screen.getByText("Укажите почту сотрудника")).toBeInTheDocument();
    expect(screen.getByText("Выберите хотя бы одну роль.")).toBeInTheDocument();
    expect(bodies).toEqual([]);
  });

  it("неверная почта — формат в подсказке", async () => {
    await setup();
    fill("Имя и фамилия", "Новый Сотрудник");
    fill("Электронная почта", "не-почта");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Снабженец/ }));

    submit();

    expect(await screen.findByText(/в формате name@company.uz/)).toBeInTheDocument();
    expect(bodies).toEqual([]);
  });

  it("«Что произойдёт» говорит про письмо и модули выбранных ролей", async () => {
    await setup();
    fireEvent.click(screen.getByRole("checkbox", { name: /^Администратор/ }));

    expect(screen.getByText(/уйдёт письмо с временным паролем/)).toBeVisible();
    expect(
      screen.getByText("Сотрудник увидит модули: Dashboard, CRM, EDS, Chats, Admin."),
    ).toBeVisible();
    expect(screen.getByText(/появится в списке со статусом «Приглашён»/)).toBeVisible();
  });

  it("отправляет данные без лишних пробелов, роли в порядке контракта", async () => {
    await setup();
    fill("Имя и фамилия", "  Новый Сотрудник ");
    fill("Электронная почта", "new@demo.example");
    fill("Должность (необязательно)", " Инженер ");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Снабженец/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Менеджер/ }));

    submit();

    await waitFor(() => {
      expect(onInvited).toHaveBeenCalledWith(created);
    });
    expect(bodies).toEqual([
      {
        email: "new@demo.example",
        name: "Новый Сотрудник",
        position: "Инженер",
        role_ids: [ROLE_ID.MANAGER, ROLE_ID.SUPPLY],
      },
    ]);
  });

  it("без должности поле не отправляется", async () => {
    await setup();
    fill("Имя и фамилия", "Новый Сотрудник");
    fill("Электронная почта", "new@demo.example");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Директор/ }));

    submit();

    await waitFor(() => {
      expect(bodies).toHaveLength(1);
    });
    expect(bodies[0]).not.toHaveProperty("position");
  });

  it("EMAIL_EXISTS — ошибка у поля почты, форма остаётся", async () => {
    server.use(
      http.post("*/admin/users/invite", () =>
        HttpResponse.json({ code: "EMAIL_EXISTS", message: "x", source: "crm" }, { status: 409 }),
      ),
    );
    await setup();
    fill("Имя и фамилия", "Новый Сотрудник");
    fill("Электронная почта", "dup@demo.example");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Директор/ }));

    submit();

    expect(await screen.findByText("Сотрудник с такой почтой уже есть.")).toBeInTheDocument();
    expect(onInvited).not.toHaveBeenCalled();
  });

  it("почта не подключена: сотрудник создан — предупреждение и «Открыть карточку»", async () => {
    server.use(
      http.post("*/admin/users/invite", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "x",
            source: "crm",
            details: { employee_id: "101", invite: "not_sent", reason: "smtp_not_configured" },
          },
          { status: 409 },
        ),
      ),
    );
    await setup();
    fill("Имя и фамилия", "Новый Сотрудник");
    fill("Электронная почта", "new@demo.example");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Директор/ }));

    submit();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/письмо не отправлено/);
    fireEvent.click(screen.getByRole("button", { name: "Открыть карточку" }));
    expect(onOpenCard).toHaveBeenCalledWith("101");
    expect(onInvited).not.toHaveBeenCalled();
  });

  it("после «письмо не отправлено» поля и роли сброшены, повторить с теми же данными нельзя", async () => {
    server.use(
      http.post("*/admin/users/invite", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "x",
            source: "crm",
            details: { employee_id: "101", invite: "not_sent", reason: "smtp_not_configured" },
          },
          { status: 409 },
        ),
      ),
    );
    await setup();
    fill("Имя и фамилия", "Новый Сотрудник");
    fill("Электронная почта", "new@demo.example");
    fill("Должность (необязательно)", "Инженер");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Директор/ }));

    submit();

    expect(await screen.findByRole("alert")).toHaveTextContent(/письмо не отправлено/);
    expect(screen.getByLabelText("Имя и фамилия")).toHaveValue("");
    expect(screen.getByLabelText("Электронная почта")).toHaveValue("");
    expect(screen.getByLabelText("Должность (необязательно)")).toHaveValue("");
    for (const box of screen.getAllByRole("checkbox")) expect(box).not.toBeChecked();
  });

  it("после успеха форма пустая, роли не накапливаются в следующем приглашении", async () => {
    await setup();
    fill("Имя и фамилия", "Первый Сотрудник");
    fill("Электронная почта", "first@demo.example");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Директор/ }));

    submit();

    await waitFor(() => {
      expect(onInvited).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByLabelText("Имя и фамилия")).toHaveValue("");
    for (const box of screen.getAllByRole("checkbox")) expect(box).not.toBeChecked();

    fill("Имя и фамилия", "Второй Сотрудник");
    fill("Электронная почта", "second@demo.example");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Снабженец/ }));
    // у кнопки ещё доигрывает анимация загрузки, и значок входит в её имя
    fireEvent.click(screen.getByRole("button", { name: /Отправить приглашение/ }));

    await waitFor(() => {
      expect(bodies).toHaveLength(2);
    });
    expect(bodies[1]?.role_ids).toEqual([ROLE_ID.SUPPLY]);
  });

  it("CRM не ответила после создания: текст про CRM, а не про почту", async () => {
    server.use(
      http.post("*/admin/users/invite", () =>
        HttpResponse.json(
          {
            code: "BACKEND_UNAVAILABLE",
            message: "x",
            source: "crm",
            details: { employee_id: "101", invite: "not_sent" },
          },
          { status: 503 },
        ),
      ),
    );
    await setup();
    fill("Имя и фамилия", "Новый Сотрудник");
    fill("Электронная почта", "new@demo.example");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Директор/ }));

    submit();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/CRM не ответила/);
    expect(alert).not.toHaveTextContent(/почта не подключена/);
    fireEvent.click(screen.getByRole("button", { name: "Открыть карточку" }));
    expect(onOpenCard).toHaveBeenCalledWith("101");
  });

  it("«Отмена» закрывает форму", async () => {
    await setup();
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
