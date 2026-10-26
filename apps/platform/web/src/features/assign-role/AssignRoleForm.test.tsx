import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import type { Employee, EmployeeUpdate } from "../../shared/api/generated/model";
import { ROLE_ID, ref, rolesHandler } from "../../test/roles";
import { server } from "../../test/server";
import { renderUi } from "../../test/renderUi";
import { AssignRoleForm } from "./AssignRoleForm";

const employee: Employee = {
  id: "11",
  name: "Анна Демова",
  initials: "АД",
  email: "anna@demo.example",
  position: "Менеджер по продажам",
  roles: [ref("MANAGER")],
  access: { crm: true, erp: true },
  status: "active",
  telegram_linked: false,
  erp_sync: "ok",
};

let sent: { id: string; body: EmployeeUpdate }[] = [];

beforeEach(() => {
  sent = [];
  server.use(
    rolesHandler(),
    http.patch("*/admin/users/:id", async ({ request, params }) => {
      const body = (await request.json()) as EmployeeUpdate;
      sent.push({ id: String(params["id"]), body });
      return HttpResponse.json(employee);
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
  it("кнопка неактивна, пока ничего не менялось; роли — из списка ролей компании", async () => {
    setup();
    expect(await screen.findByRole("checkbox", { name: /^Менеджер/ })).toBeChecked();
    expect(save()).toBeDisabled();
    // Системные роли подписаны словами.
    expect(screen.getByRole("checkbox", { name: /^Директор.*системная роль/ })).not.toBeChecked();
  });

  it("«Что произойдёт» строится из матриц ролей: модули новых ролей и потерянные", async () => {
    setup({ employee: { ...employee, roles: [ref("ADMIN")] } });

    fireEvent.click(await screen.findByRole("checkbox", { name: /^Администратор/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Снабженец/ }));

    const block = screen.getByRole("group", { name: "Что произойдёт" });
    expect(
      within(block).getByText("Сотрудник увидит модули: Dashboard, CRM, EDS, ERP, Chats."),
    ).toBeVisible();
    expect(within(block).getByText("Перестанет видеть модули: Admin.")).toBeVisible();
    expect(
      within(block).getByText(/В ERP сотрудник получит права по разделам ролей/),
    ).toBeVisible();
  });

  it("созданная роль с Admin «полный»: предупреждение, что полного администратора CRM она не даёт", async () => {
    server.use(
      rolesHandler([
        {
          id: "42",
          name: "Офис-менеджер",
          description: "",
          system: false,
          version: 1,
          access: { admin: "full", "chats.internal": "full" },
          restricted_fields: [],
          employees: 0,
          updated_at: "2026-10-23T09:00:00Z",
        },
      ]),
    );
    setup();

    fireEvent.click(await screen.findByRole("checkbox", { name: /^Офис-менеджер/ }));

    expect(
      screen.getByText(/не суперпользователя ERP: его даёт только системная роль «Администратор»/),
    ).toBeVisible();
  });

  it("отправляет только изменённые поля: полный набор id ролей в порядке списка", async () => {
    setup();

    fireEvent.click(await screen.findByRole("checkbox", { name: /^Бухгалтер/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Директор/ }));
    fireEvent.click(save());

    await waitFor(() => {
      expect(sent).toEqual([
        {
          id: "11",
          body: { role_ids: [ROLE_ID.DIRECTOR, ROLE_ID.MANAGER, ROLE_ID.ACCOUNTANT] },
        },
      ]);
    });
  });

  it("должность: обрезается, пустая очищает, в блоке — что изменится", async () => {
    setup();
    await screen.findByRole("checkbox", { name: /^Менеджер/ });
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

  it("без ролей сохранить нельзя: подсказка про отключение", async () => {
    setup();

    fireEvent.click(await screen.findByRole("checkbox", { name: /^Менеджер/ }));

    expect(save()).toBeDisabled();
    expect(screen.getByText(/Выберите хотя бы одну роль/)).toBeVisible();
    expect(sent).toEqual([]);
  });

  it("снять роль у единственного администратора нельзя: текст и неактивная кнопка", async () => {
    setup({
      employee: { ...employee, id: "7", roles: [ref("ADMIN")] },
      otherActiveAdmins: 0,
    });

    fireEvent.click(await screen.findByRole("checkbox", { name: /^Менеджер/ }));
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
    setup({ employee: { ...employee, id: "7", roles: [ref("ADMIN")] }, otherActiveAdmins: 1 });

    fireEvent.click(await screen.findByRole("checkbox", { name: /^Менеджер/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Администратор/ }));
    fireEvent.click(save());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/последнего администратора/);
  });

  it("лиды в работе: выбор коллеги и повтор с transfer_to_user_id", async () => {
    let attempt = 0;
    server.use(
      http.get("*/admin/users", () =>
        HttpResponse.json({
          items: [employee, { ...employee, id: "12", name: "Борис Коллегин" }],
        }),
      ),
      http.patch("*/admin/users/:id", async ({ request }) => {
        const body = (await request.json()) as EmployeeUpdate;
        sent.push({ id: "11", body });
        attempt += 1;
        if (attempt === 1) {
          return HttpResponse.json(
            {
              code: "CONFLICT",
              message: "x",
              source: "crm",
              details: { reason: "user_has_active_leads" },
            },
            { status: 409 },
          );
        }
        return HttpResponse.json(employee);
      }),
    );
    setup();

    fireEvent.click(await screen.findByRole("checkbox", { name: /^Снабженец/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Менеджер/ }));
    fireEvent.click(save());

    expect(await screen.findByRole("alert")).toHaveTextContent(/лиды в работе/);
    const transfer = await screen.findByRole("button", { name: /Передать лиды и сохранить$/ });
    await waitFor(() => {
      expect(transfer).toBeDisabled();
    });
    const colleague = screen.getByLabelText("Кому передать лиды в работе");
    await screen.findByRole("option", { name: "Борис Коллегин" });
    fireEvent.change(colleague, { target: { value: "12" } });
    fireEvent.click(transfer);

    await waitFor(() => {
      expect(sent[1]?.body).toEqual({ role_ids: [ROLE_ID.SUPPLY], transfer_to_user_id: "12" });
    });
  });

  it("свои роли: в блоке предупреждение про меню", async () => {
    setup({ employee: { ...employee, id: "7" } });

    fireEvent.click(await screen.findByRole("checkbox", { name: /^Снабженец/ }));

    expect(screen.getByText(/Вы меняете собственные роли/)).toBeVisible();
  });
});
