import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import type { Employee, EmployeeUpdate } from "../../shared/api/generated/model";
import { server } from "../../test/server";
import { renderUi } from "../../test/renderUi";
import { AssignRoleForm } from "./AssignRoleForm";

const employee: Employee = {
  id: "11",
  name: "Анна Демова",
  initials: "АД",
  email: "anna@demo.example",
  position: "Менеджер по продажам",
  roles: ["MANAGER"],
  access: { crm: true, erp: true },
  status: "active",
  telegram_linked: false,
  erp_sync: "ok",
};

let sent: { id: string; body: EmployeeUpdate }[] = [];

beforeEach(() => {
  sent = [];
  server.use(
    http.patch("*/admin/users/:id", async ({ request, params }) => {
      const body = (await request.json()) as EmployeeUpdate;
      sent.push({ id: String(params["id"]), body });
      return HttpResponse.json({ ...employee, roles: body.roles ?? employee.roles });
    }),
  );
});

function setup(props: Partial<Parameters<typeof AssignRoleForm>[0]> = {}) {
  return renderUi(
    <AssignRoleForm employee={employee} selfId="7" otherActiveAdmins={1} {...props} />,
  );
}

const save = () => screen.getByRole("button", { name: "Сохранить роли" });

describe("AssignRoleForm: выдача ролей", () => {
  it("кнопка неактивна, пока ничего не менялось", () => {
    setup();
    expect(save()).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /^Менеджер/ })).toBeChecked();
  });

  it("«Что произойдёт» строится из матрицы: модули новых ролей и потерянные", () => {
    setup({ employee: { ...employee, roles: ["ADMIN"] } });

    fireEvent.click(screen.getByRole("checkbox", { name: /^Администратор/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Снабженец/ }));

    const block = screen.getByRole("group", { name: "Что произойдёт" });
    expect(
      within(block).getByText("Сотрудник увидит модули: Dashboard, CRM, EDS, ERP, Chats."),
    ).toBeVisible();
    expect(within(block).getByText("Перестанет видеть модули: Admin.")).toBeVisible();
    expect(
      within(block).getByText(
        "В ERP сотрудник получит роли: Каталог и закупки, Исполнение и логистика.",
      ),
    ).toBeVisible();
  });

  it("отправляет только изменённые поля: роли в порядке контракта", async () => {
    setup();

    fireEvent.click(screen.getByRole("checkbox", { name: /^Бухгалтер/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Директор/ }));
    fireEvent.click(save());

    await waitFor(() => {
      expect(sent).toEqual([{ id: "11", body: { roles: ["MANAGER", "DIRECTOR", "ACCOUNTANT"] } }]);
    });
  });

  it("должность: обрезается, пустая очищает, в блоке — что изменится", async () => {
    setup();
    const input = screen.getByLabelText("Должность");

    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByText("Должность в карточке будет очищена.")).toBeVisible();
    fireEvent.change(input, { target: { value: "  Старший менеджер " } });
    expect(screen.getByText("Должность в карточке: «Старший менеджер».")).toBeVisible();
    fireEvent.click(save());

    await waitFor(() => {
      expect(sent[0]?.body).toEqual({ position: "Старший менеджер" });
    });
  });

  it("без ролей сохранить нельзя: подсказка про отключение", () => {
    setup();

    fireEvent.click(screen.getByRole("checkbox", { name: /^Менеджер/ }));

    expect(save()).toBeDisabled();
    expect(screen.getByText(/Выберите хотя бы одну роль/)).toBeVisible();
    expect(sent).toEqual([]);
  });

  it("снять роль у единственного администратора нельзя: текст и неактивная кнопка", () => {
    setup({
      employee: { ...employee, id: "7", roles: ["ADMIN"] },
      otherActiveAdmins: 0,
    });

    fireEvent.click(screen.getByRole("checkbox", { name: /^Менеджер/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Администратор/ }));

    expect(screen.getByText(/Вы единственный администратор/)).toBeVisible();
    expect(save()).toBeDisabled();
    // при запрете — только причина, без обещаний «что произойдёт»
    expect(screen.queryByRole("group", { name: "Что произойдёт" })).toBeNull();
    expect(screen.queryByText(/Сотрудник увидит модули/)).toBeNull();
    // форма не отправляется и по Enter в поле должности
    fireEvent.submit(save().closest("form") as HTMLFormElement);
    expect(sent).toEqual([]);
  });

  it("CRM ответила 409 LAST_ADMIN (список устарел) — текст ошибки у кнопки", async () => {
    server.use(
      http.patch("*/admin/users/:id", () =>
        HttpResponse.json(
          {
            code: "LAST_ADMIN",
            message: "x",
            source: "crm",
            details: { backend_code: "last_admin" },
          },
          { status: 409 },
        ),
      ),
    );
    setup({ employee: { ...employee, id: "7", roles: ["ADMIN"] }, otherActiveAdmins: 1 });

    fireEvent.click(screen.getByRole("checkbox", { name: /^Менеджер/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Администратор/ }));
    fireEvent.click(save());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/последнего администратора/);
  });

  it("лиды в работе: 409 CONFLICT объясняется отдельным текстом", async () => {
    server.use(
      http.patch("*/admin/users/:id", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "x",
            source: "crm",
            details: { backend_code: "user_has_active_leads" },
          },
          { status: 409 },
        ),
      ),
    );
    setup();

    fireEvent.click(screen.getByRole("checkbox", { name: /^Директор/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Менеджер/ }));
    fireEvent.click(save());

    expect(await screen.findByRole("alert")).toHaveTextContent(/лиды в работе/);
  });

  it("свои роли: в блоке предупреждение про меню", () => {
    setup({ employee: { ...employee, id: "7" } });

    fireEvent.click(screen.getByRole("checkbox", { name: /^Снабженец/ }));

    expect(screen.getByText(/Вы меняете собственные роли/)).toBeVisible();
  });
});
