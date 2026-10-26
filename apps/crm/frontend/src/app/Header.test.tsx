import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { t } from "../i18n/ru";
import { Header } from "./Header";

type Identity =
  { name: string; sso_enabled?: boolean; platform_access?: string[] | undefined } | undefined;
const state = vi.hoisted(() => ({
  identity: undefined as Identity,
  canSystem: false,
  stream: true,
  live: true,
  systemStatus: undefined as { status: string; components: never[] } | undefined,
}));
const eventStream = vi.hoisted(() => vi.fn());
const ssoToken = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useGetIdentity: () => ({ data: state.identity }),
  useCan: () => ({ data: { can: state.canSystem } }),
}));
vi.mock("@refinedev/antd", () => ({
  useThemedLayoutContext: () => ({ setMobileSiderOpen: vi.fn() }),
}));
vi.mock("../api/adminQueries", () => ({
  useSystemStatus: () => ({ data: state.systemStatus }),
}));
vi.mock("../api/queries", () => ({
  usePermissionsQuery: () => ({
    data: { permissions: { stream: { read: state.stream } } },
  }),
}));
vi.mock("../api/generated/crm", () => ({ ssoToken }));
vi.mock("../hooks/useEventStream", () => ({
  useEventStream: (enabled: boolean) => {
    eventStream(enabled);
    return state.live;
  },
}));
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
  state.stream = true;
  state.live = true;
  state.systemStatus = undefined;
  eventStream.mockReset();
  ssoToken.mockReset();
});
afterEach(cleanup);

describe("Header — индикатор связи и поток (W11B-G-3)", () => {
  it("с правом на поток: подписка включена, индикатор показывает состояние", () => {
    state.identity = { name: "Менеджер" };
    state.live = false;
    renderHeader();
    expect(eventStream).toHaveBeenLastCalledWith(true);
    expect(screen.getAllByRole("status")[0]?.textContent).toContain("Нет связи");
  });

  it("без права на поток: подписки нет, индикатора связи нет", () => {
    state.identity = { name: "Менеджер" };
    state.stream = false;
    state.live = false;
    renderHeader();
    expect(eventStream).toHaveBeenLastCalledWith(false);
    expect(screen.queryByText("Нет связи")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("пока профиль не загружен, подписки нет", () => {
    renderHeader();
    expect(eventStream).toHaveBeenLastCalledWith(false);
  });

  it("администратор без права на поток: нет «Нет связи», здоровье системы показано по HTTP", () => {
    state.canSystem = true;
    state.stream = false;
    state.live = false;
    state.identity = { name: "Админ" };
    state.systemStatus = { status: "ok", components: [] };
    renderHeader();
    expect(eventStream).toHaveBeenLastCalledWith(false);
    expect(screen.queryByText("Нет связи")).toBeNull();
    expect(screen.getByText(t.health.ok)).toBeInTheDocument();
  });
});

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
