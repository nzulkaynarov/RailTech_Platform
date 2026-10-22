import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import type { Employee, EmployeeUpdate } from "../../shared/api/generated/model";
import { server } from "../../test/server";
import { renderUi } from "../../test/renderUi";
import { DisableEmployee } from "./DisableEmployee";

const employee: Employee = {
  id: "11",
  name: "Анна Демова",
  initials: "АД",
  email: "anna@demo.example",
  roles: ["MANAGER"],
  access: { crm: true, erp: true },
  status: "active",
  telegram_linked: false,
  erp_sync: "ok",
};

let sent: EmployeeUpdate[] = [];

beforeEach(() => {
  sent = [];
  server.use(
    http.patch("*/admin/users/:id", async ({ request }) => {
      const body = (await request.json()) as EmployeeUpdate;
      sent.push(body);
      return HttpResponse.json({ ...employee, status: body.is_active ? "active" : "disabled" });
    }),
  );
});

describe("DisableEmployee", () => {
  it("отключение — с подтверждением и блоком «Что произойдёт»", async () => {
    renderUi(<DisableEmployee employee={employee} selfId="7" otherActiveAdmins={1} />);

    fireEvent.click(screen.getByRole("button", { name: "Отключить сотрудника" }));
    expect(sent).toEqual([]);
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    expect(screen.getByText("Вход в Платформу, CRM и ERP закроется.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Отключить" }));

    await waitFor(() => {
      expect(sent).toEqual([{ is_active: false }]);
    });
  });

  it("отмена не отправляет запрос", () => {
    renderUi(<DisableEmployee employee={employee} selfId="7" otherActiveAdmins={1} />);

    fireEvent.click(screen.getByRole("button", { name: "Отключить сотрудника" }));
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));

    expect(screen.getByRole("button", { name: "Отключить сотрудника" })).toBeVisible();
    expect(sent).toEqual([]);
  });

  it("отключённого можно включить", async () => {
    renderUi(
      <DisableEmployee
        employee={{ ...employee, status: "disabled" }}
        selfId="7"
        otherActiveAdmins={1}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Включить сотрудника" }));
    fireEvent.click(screen.getByRole("button", { name: "Включить" }));

    await waitFor(() => {
      expect(sent).toEqual([{ is_active: true }]);
    });
  });

  it("последнего администратора отключить нельзя: текст и неактивная кнопка", () => {
    renderUi(
      <DisableEmployee
        employee={{ ...employee, id: "7", roles: ["ADMIN"] }}
        selfId="7"
        otherActiveAdmins={0}
      />,
    );

    expect(screen.getByRole("button", { name: "Отключить сотрудника" })).toBeDisabled();
    expect(
      screen.getByText(/нельзя снять роль администратора или отключить последнего/i),
    ).toBeVisible();
  });

  it("409 LAST_ADMIN от CRM — понятная ошибка", async () => {
    server.use(
      http.patch("*/admin/users/:id", () =>
        HttpResponse.json({ code: "LAST_ADMIN", message: "x", source: "crm" }, { status: 409 }),
      ),
    );
    renderUi(
      <DisableEmployee
        employee={{ ...employee, roles: ["ADMIN"] }}
        selfId="7"
        otherActiveAdmins={1}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Отключить сотрудника" }));
    fireEvent.click(screen.getByRole("button", { name: "Отключить" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/последнего администратора/);
  });
});
