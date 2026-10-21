import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UserOut } from "../../api/generated/model";
import { EditUserDialog } from "./UserDialogs";
import { ErpGrantDialog } from "./ErpRoles";

const user = (patch: Partial<UserOut> = {}): UserOut =>
  ({
    id: 4,
    email: "m@railtech.uz",
    full_name: "Менеджер",
    roles: ["manager"],
    is_active: true,
    tg_user_id: null,
    platform_access: ["crm", "erp"],
    erp_role_codes: ["FINANCE"],
    ...patch,
  }) as unknown as UserOut;

const wrap = (node: React.ReactNode) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AntApp>{node}</AntApp>
    </QueryClientProvider>,
  );
};

afterEach(cleanup);

const group = () => screen.getByRole("group", { name: "Роли в ERP" });
const box = (name: string) =>
  within(group()).getByRole("checkbox", { name: new RegExp(`^${name}`) });

describe("EditUserDialog — роли ERP (FIX-63)", () => {
  it("у пользователя с доступом к ERP есть выбор ролей ERP с выданными ролями", () => {
    wrap(<EditUserDialog user={user()} saving={false} onCancel={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.getByText("Роли в ERP")).toBeInTheDocument();
    expect(group()).toBeInTheDocument();
    expect(box("Финансы")).toBeChecked();
    expect(box("Расчёт")).not.toBeChecked();
  });

  it("без доступа к ERP выбора ролей нет", () => {
    wrap(
      <EditUserDialog
        user={user({ platform_access: ["crm"], erp_role_codes: [] })}
        saving={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.queryByText("Роли в ERP")).toBeNull();
  });

  it("изменение ролей уходит в erp_role_codes вместе с остальными полями", async () => {
    const onSubmit = vi.fn();
    wrap(<EditUserDialog user={user()} saving={false} onCancel={vi.fn()} onSubmit={onSubmit} />);

    fireEvent.click(box("Расчёт"));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({
      full_name: "Менеджер",
      erp_role_codes: ["CALCULATION", "FINANCE"],
    });
  });

  it("поле «Роли» CRM обязательно, но без aria-required на корне Select (axe aria-allowed-attr)", async () => {
    const onSubmit = vi.fn();
    wrap(<EditUserDialog user={user()} saving={false} onCancel={vi.fn()} onSubmit={onSubmit} />);
    expect(document.querySelector(".ant-select[aria-required]")).toBeNull();

    // снять единственную роль — сохранить нельзя
    const rolesSelect = screen.getAllByRole("combobox")[0] as HTMLElement;
    const remove = rolesSelect
      .closest(".ant-select")
      ?.querySelector(".ant-select-selection-item-remove");
    fireEvent.click(remove as Element);
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByText("Выберите хотя бы одну роль")).toBeInTheDocument();
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("у администратора CRM выбор ролей закрыт: он суперпользователь ERP", () => {
    wrap(
      <EditUserDialog
        user={user({ roles: ["admin"] })}
        saving={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(box("Расчёт")).toBeDisabled();
    expect(screen.getByText(/суперпользователь ERP/)).toBeInTheDocument();
  });
});

describe("ErpGrantDialog — выдача доступа к ERP с выбором ролей (FIX-63)", () => {
  it("закрыт, пока пользователь не выбран", () => {
    wrap(<ErpGrantDialog user={null} saving={false} onCancel={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("показывает, кому выдаётся доступ, и список ролей с понятными названиями", () => {
    wrap(
      <ErpGrantDialog
        user={user({ platform_access: ["crm"], erp_role_codes: [] })}
        saving={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText("Выдать доступ к ERP: Менеджер")).toBeInTheDocument();
    const expected = [
      "Расчёт",
      "Каталог и закупки",
      "Исполнение и логистика",
      "Финансы",
      "Руководитель",
      "Наблюдатель",
    ];
    const boxes = within(group()).getAllByRole("checkbox");
    expect(boxes).toHaveLength(expected.length);
    expected.forEach((name, index) => {
      expect(boxes[index]).toHaveAccessibleName(new RegExp(`^${name}`));
    });
    expect(screen.getByText(/утверждение КП/)).toBeInTheDocument(); // подсказка к «Руководителю»
  });

  it("выдача без ролей — пустой список; с ролями — выбранные", async () => {
    const onSubmit = vi.fn();
    wrap(
      <ErpGrantDialog
        user={user({ platform_access: ["crm"], erp_role_codes: [] })}
        saving={false}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(box("Руководитель"));
    fireEvent.click(screen.getByRole("button", { name: "Выдать доступ" }));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(["HEAD"]);
    });
  });

  it("начальный выбор — роли, сохранённые у пользователя ранее", async () => {
    const onSubmit = vi.fn();
    wrap(
      <ErpGrantDialog
        user={user({ platform_access: ["crm"], erp_role_codes: ["VIEWER"] })}
        saving={false}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Выдать доступ" }));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(["VIEWER"]);
    });
  });
});
