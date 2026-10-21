import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { UserOut } from "../../api/generated/model";
import { UsersPage } from "./UsersPage";

const { updateUser, users } = vi.hoisted(() => ({
  updateUser: vi.fn(),
  users: { current: [] as unknown[] },
}));

vi.mock("../../api/generated/crm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/generated/crm")>();
  return { ...actual, updateUser };
});
vi.mock("../../api/queries", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/queries")>();
  return {
    ...actual,
    useUsers: () => ({
      data: users.current,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    }),
    useTeam: () => ({ data: [] }),
  };
});

const user = (patch: Partial<UserOut> = {}): UserOut =>
  ({
    id: 4,
    email: "m@railtech.uz",
    full_name: "Менеджер",
    roles: ["manager"],
    is_active: true,
    tg_user_id: null,
    platform_access: ["crm"],
    erp_role_codes: [],
    ...patch,
  }) as unknown as UserOut;

const renderPage = () =>
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AntApp>
        <MemoryRouter>
          <UsersPage />
        </MemoryRouter>
      </AntApp>
    </QueryClientProvider>,
  );

const box = (name: string) =>
  within(screen.getByRole("group", { name: "Роли в ERP" })).getByRole("checkbox", {
    name: new RegExp(`^${name}`),
  });

beforeEach(() => {
  updateUser.mockReset();
  updateUser.mockResolvedValue({});
  users.current = [user()];
});
afterEach(cleanup);

describe("UsersPage — выдача доступа к ERP с ролями (FIX-63)", () => {
  it("включение переключателя открывает выбор ролей ERP, а не выдаёт доступ сразу", () => {
    renderPage();
    fireEvent.click(screen.getByRole("switch", { name: "Доступ к ERP: Менеджер" }));
    expect(screen.getByText("Выдать доступ к ERP: Менеджер")).toBeInTheDocument();
    expect(updateUser).not.toHaveBeenCalled();
  });

  it("«Выдать доступ» отправляет platform_access и выбранные роли одним запросом", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("switch", { name: "Доступ к ERP: Менеджер" }));
    fireEvent.click(box("Расчёт"));
    fireEvent.click(box("Финансы"));
    fireEvent.click(screen.getByRole("button", { name: "Выдать доступ" }));

    await waitFor(() => {
      expect(updateUser).toHaveBeenCalledWith(4, {
        platform_access: ["crm", "erp"],
        erp_role_codes: ["CALCULATION", "FINANCE"],
      });
    });
  });

  it("отмена выдачи ничего не отправляет", () => {
    renderPage();
    fireEvent.click(screen.getByRole("switch", { name: "Доступ к ERP: Менеджер" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Отмена" }));
    expect(updateUser).not.toHaveBeenCalled();
  });

  it("снятие доступа — как раньше, только platform_access (роли остаются в CRM на будущее)", async () => {
    users.current = [user({ platform_access: ["crm", "erp"], erp_role_codes: ["HEAD"] })];
    renderPage();
    fireEvent.click(screen.getByRole("switch", { name: "Доступ к ERP: Менеджер" }));
    fireEvent.click(await screen.findByRole("button", { name: "Снять доступ" }));
    await waitFor(() => {
      expect(updateUser).toHaveBeenCalledWith(4, { platform_access: ["crm"] });
    });
  });

  it("сохранение ролей ERP в карточке показывает отдельное подтверждение", async () => {
    users.current = [user({ platform_access: ["crm", "erp"], erp_role_codes: ["FINANCE"] })];
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Менеджер" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /^Расчёт/ }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(updateUser).toHaveBeenCalledWith(
        4,
        expect.objectContaining({ erp_role_codes: ["CALCULATION", "FINANCE"] }),
      );
    });
    expect(await screen.findByText(/Роли ERP сохранены: Менеджер/)).toBeInTheDocument();
  });

  it("без изменения ролей ERP — обычное «Пользователь сохранён»", async () => {
    users.current = [user({ platform_access: ["crm", "erp"], erp_role_codes: ["FINANCE"] })];
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Менеджер" }));
    fireEvent.click(await screen.findByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Пользователь Менеджер сохранён")).toBeInTheDocument();
    expect(screen.queryByText(/Роли ERP сохранены/)).toBeNull();
  });
});
