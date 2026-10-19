import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UserOut } from "../../api/generated/model";
import { UsersTable } from "./UsersTable";

const user = (patch: Partial<UserOut>): UserOut =>
  ({
    id: 1,
    email: "m@railtech.uz",
    full_name: "Менеджер",
    roles: ["manager"],
    is_active: true,
    tg_user_id: null,
    platform_access: ["crm"],
    ...patch,
  }) as unknown as UserOut;

const noop = vi.fn();
const renderTable = (
  data: UserOut[],
  onToggleErp = vi.fn(),
  erpPendingId: number | null = null,
) => {
  render(
    <UsersTable
      data={data}
      loading={false}
      onEdit={noop}
      onReset={noop}
      onInvite={noop}
      onResetByEmail={noop}
      onToggleErp={onToggleErp}
      erpPendingId={erpPendingId}
    />,
  );
  return onToggleErp;
};
const erpSwitch = (name = "Менеджер") =>
  screen.getByRole("switch", { name: `Доступ к ERP: ${name}` });

afterEach(cleanup);

describe("UsersTable — «Доступ к ERP» (FIX-11)", () => {
  it("по умолчанию выключен: у пользователя только CRM", () => {
    renderTable([user({})]);
    expect(erpSwitch()).not.toBeChecked();
  });

  it("включён, когда в platform_access есть erp", () => {
    renderTable([user({ platform_access: ["crm", "erp"] })]);
    expect(erpSwitch()).toBeChecked();
  });

  it("выдача и снятие уходят в обработчик с новым значением", () => {
    const toggle = renderTable([
      user({}),
      user({ id: 2, full_name: "Админ", platform_access: ["crm", "erp"] }),
    ]);
    fireEvent.click(erpSwitch("Менеджер"));
    fireEvent.click(erpSwitch("Админ"));
    expect(toggle).toHaveBeenNthCalledWith(1, expect.objectContaining({ id: 1 }), true);
    expect(toggle).toHaveBeenNthCalledWith(2, expect.objectContaining({ id: 2 }), false);
  });

  it("неактивному без доступа выдать ERP нельзя", () => {
    const toggle = renderTable([user({ is_active: false })]);
    expect(erpSwitch()).toBeDisabled();
    fireEvent.click(erpSwitch());
    expect(toggle).not.toHaveBeenCalled();
  });

  it("у неактивного с доступом снять можно", () => {
    renderTable([user({ is_active: false, platform_access: ["crm", "erp"] })]);
    expect(erpSwitch()).toBeEnabled();
  });

  it("пока сохраняется, переключатель заблокирован", () => {
    renderTable([user({})], vi.fn(), 1);
    expect(erpSwitch()).toBeDisabled();
  });
});
