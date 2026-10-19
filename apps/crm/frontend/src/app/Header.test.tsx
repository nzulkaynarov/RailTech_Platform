import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Header } from "./Header";

type Identity =
  { name: string; sso_enabled?: boolean; platform_access?: string[] | undefined } | undefined;
const state = vi.hoisted(() => ({ identity: undefined as Identity, canSystem: false }));
const ssoToken = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useGetIdentity: () => ({ data: state.identity }),
  useCan: () => ({ data: { can: state.canSystem } }),
}));
vi.mock("@refinedev/antd", () => ({
  useThemedLayoutContext: () => ({ setMobileSiderOpen: vi.fn() }),
}));
vi.mock("../api/adminQueries", () => ({ useSystemStatus: () => ({ data: undefined }) }));
vi.mock("../api/generated/crm", () => ({ ssoToken }));
vi.mock("../hooks/useEventStream", () => ({ useEventStream: () => true }));
vi.mock("../hooks/useLeadAlerts", () => ({ useLeadAlertHandler: () => vi.fn() }));
vi.mock("../components/ModeSwitch", () => ({ ModeSwitch: () => null }));
vi.mock("./UserMenu", () => ({ UserMenu: () => null }));

const renderHeader = () =>
  render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>,
  );
const erpButton = () => screen.queryByRole("button", { name: "В бэк-офис (ERP)" });

beforeEach(() => {
  state.identity = undefined;
  state.canSystem = false;
  ssoToken.mockReset();
});
afterEach(cleanup);

describe("Header — переход в ERP (FIX-11)", () => {
  it.each([
    { sso_enabled: true, platform_access: ["crm", "erp"], shown: true },
    { sso_enabled: true, platform_access: ["crm"], shown: false },
    { sso_enabled: false, platform_access: ["crm", "erp"], shown: false },
    { sso_enabled: false, platform_access: ["crm"], shown: false },
    { sso_enabled: true, platform_access: undefined, shown: false },
  ])("кнопка при %j", ({ shown, ...access }) => {
    state.identity = { name: "Менеджер", ...access };
    renderHeader();
    expect(erpButton() !== null).toBe(shown);
  });

  it("не показана, пока профиль не загружен", () => {
    renderHeader();
    expect(erpButton()).toBeNull();
  });

  it("админ без выданного доступа к ERP тоже не видит кнопку", () => {
    state.canSystem = true;
    state.identity = { name: "Админ", sso_enabled: true, platform_access: ["crm"] };
    renderHeader();
    expect(erpButton()).toBeNull();
  });

  it("при доступе запрашивает токен и уходит в ERP с фрагментом #token", async () => {
    state.identity = { name: "Менеджер", sso_enabled: true, platform_access: ["crm", "erp"] };
    ssoToken.mockResolvedValue({
      token: "jwt-value",
      redirect_url: "http://erp.localhost/sso/exchange",
    });
    const location = { href: "" };
    vi.stubGlobal("location", location);
    renderHeader();

    fireEvent.click(erpButton() as HTMLElement);

    await waitFor(() => {
      expect(location.href).toBe("http://erp.localhost/sso/exchange#token=jwt-value");
    });
    vi.unstubAllGlobals();
  });
});
