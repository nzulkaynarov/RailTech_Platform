import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation, type Location } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";

import type { SectionConfig } from "../../modules/types";
import { panelsKey, usePanelsStore } from "./panelsStore";
import { usePanels } from "./usePanels";

const mockSection: SectionConfig = {
  key: "crm.leads",
  path: "/crm/leads",
  access: { resource: "crm.leads" },
  tabs: [{ key: "card" }, { key: "history" }, { key: "tasks" }],
};

const chatsSection: SectionConfig = {
  key: "chats.inbox",
  path: "/chats/inbox",
  access: { resource: "chats.inbox" },
  tabs: [{ key: "card" }],
};

function createWrapper(initialUrl = "/crm/leads") {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[initialUrl]}>{children}</MemoryRouter>;
  };
}

describe("usePanels", () => {
  beforeEach(() => {
    window.localStorage.clear();
    usePanelsStore.setState({ entries: {} });
  });

  it("разделение состояния: по умолчанию панель закрыта без ?panel=open в URL, даже если в storage есть данные", () => {
    const key = panelsKey("user-1", "/crm/leads");
    usePanelsStore.setState({
      entries: {
        [key]: {
          menuOpen: true,
          panelMode: "overlay",
          panelWidth: "default",
          lastTab: "history",
        },
      },
    });

    const { result } = renderHook(() => usePanels("user-1", mockSection), {
      wrapper: createWrapper("/crm/leads"),
    });

    // Панель закрыта, так как в URL нет ?panel=open
    expect(result.current.panelOpen).toBe(false);
    // lastTab подтягивается из storage
    expect(result.current.tab).toBe("history");
    expect(result.current.panelMode).toBe("overlay");
  });

  it("открывается при наличии ?panel=open в URL", () => {
    const { result } = renderHook(() => usePanels("user-1", mockSection), {
      wrapper: createWrapper("/crm/leads?panel=open"),
    });

    expect(result.current.panelOpen).toBe(true);
  });

  it("setPanelOpen(true) и setPanelOpen(false) корректно синхронизируют URL", () => {
    const locRef = { current: null as Location | null };
    function LocationTracker() {
      locRef.current = useLocation();
      return null;
    }

    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <MemoryRouter initialEntries={["/crm/leads"]}>
          <LocationTracker />
          {children}
        </MemoryRouter>
      );
    }

    const { result } = renderHook(() => usePanels("user-1", mockSection), { wrapper: Wrapper });

    expect(result.current.panelOpen).toBe(false);

    // Открываем панель
    act(() => {
      result.current.setPanelOpen(true);
    });

    expect(result.current.panelOpen).toBe(true);
    expect(locRef.current?.search).toContain("panel=open");

    // Закрываем панель
    act(() => {
      result.current.setPanelOpen(false);
    });

    expect(result.current.panelOpen).toBe(false);
    expect(locRef.current?.search).not.toContain("panel=open");
  });

  it("переключение panelMode (overlay / docked) сохраняется в panelsStore", () => {
    const key = panelsKey("user-1", "/crm/leads");
    const { result } = renderHook(() => usePanels("user-1", mockSection), {
      wrapper: createWrapper("/crm/leads?panel=open"),
    });

    expect(result.current.panelMode).toBe("overlay");

    act(() => {
      result.current.setPanelMode("docked");
    });

    expect(result.current.panelMode).toBe("docked");
    expect(usePanelsStore.getState().entries[key]?.panelMode).toBe("docked");

    act(() => {
      result.current.setPanelMode("overlay");
    });

    expect(result.current.panelMode).toBe("overlay");
    expect(usePanelsStore.getState().entries[key]?.panelMode).toBe("overlay");
  });

  it("в разделе chats panelMode строго зафиксирован как overlay", () => {
    const key = panelsKey("user-1", "/chats/inbox");
    const { result } = renderHook(() => usePanels("user-1", chatsSection), {
      wrapper: createWrapper("/chats/inbox?panel=open"),
    });

    expect(result.current.panelMode).toBe("overlay");

    act(() => {
      result.current.setPanelMode("docked");
    });

    // Режим остаётся overlay
    expect(result.current.panelMode).toBe("overlay");
    expect(usePanelsStore.getState().entries[key]?.panelMode).toBeUndefined();
  });

  it("переключение panelWidth (default / wide) сохраняется в panelsStore", () => {
    const key = panelsKey("user-1", "/crm/leads");
    const { result } = renderHook(() => usePanels("user-1", mockSection), {
      wrapper: createWrapper("/crm/leads?panel=open"),
    });

    expect(result.current.panelWidth).toBe("default");

    act(() => {
      result.current.setPanelWidth("wide");
    });

    expect(result.current.panelWidth).toBe("wide");
    expect(usePanelsStore.getState().entries[key]?.panelWidth).toBe("wide");
  });

  it("вид по умолчанию — поверх везде, и на карточке объекта (решение 2026-10-30, п. 2); булавка — выбор пользователя", () => {
    const list = renderHook(() => usePanels("user-1", mockSection), {
      wrapper: createWrapper("/crm/leads"),
    });
    expect(list.result.current.panelMode).toBe("overlay");

    const card = renderHook(() => usePanels("user-1", mockSection, true), {
      wrapper: createWrapper("/crm/leads/L-2041"),
    });
    expect(card.result.current.panelMode).toBe("overlay");
    // 600 px — не умолчание раздела, а выбор «Шире»
    expect(card.result.current.panelWidth).toBe("default");
    act(() => {
      card.result.current.setPanelMode("docked");
    });
    expect(card.result.current.panelMode).toBe("docked");
  });

  it("подменю — одно значение на пользователя: переход между разделами его не меняет", () => {
    const calc: SectionConfig = {
      key: "erp.calc",
      path: "/erp/calc",
      access: { resource: "erp.calc" },
    };
    const leads = renderHook(() => usePanels("user-1", mockSection), {
      wrapper: createWrapper("/crm/leads"),
    });
    // matchMedia в jsdom ничему не отвечает «да» — экран узкий, по умолчанию свёрнуто
    expect(leads.result.current.menuOpen).toBe(false);
    act(() => {
      leads.result.current.toggleMenu();
    });
    expect(leads.result.current.menuOpen).toBe(true);

    const other = renderHook(() => usePanels("user-1", calc), {
      wrapper: createWrapper("/erp/calc"),
    });
    expect(other.result.current.menuOpen).toBe(true);
    expect(usePanelsStore.getState().entries[panelsKey("user-1", "*")]?.menuOpen).toBe(true);
    expect(usePanelsStore.getState().entries[panelsKey("user-1", "/crm/leads")]).toBeUndefined();

    // другой пользователь — своё значение
    const stranger = renderHook(() => usePanels("user-2", calc), {
      wrapper: createWrapper("/erp/calc"),
    });
    expect(stranger.result.current.menuOpen).toBe(false);
  });

  it("v2 с подменю по разделу читается совместимо: выбор, сделанный чаще, переносится на пользователя", () => {
    window.localStorage.setItem(
      "rt-pf-panels-v2",
      JSON.stringify({
        "user-1|/crm/leads": { menuOpen: true, lastTab: "history" },
        "user-1|/erp/calc": { menuOpen: false },
        "user-1|/eds/inbox": { menuOpen: true, panelMode: "docked" },
        "user-2|/erp/calc": { menuOpen: false },
      }),
    );
    usePanelsStore.getState().reload();

    const calc: SectionConfig = {
      key: "erp.calc",
      path: "/erp/calc",
      access: { resource: "erp.calc" },
    };
    const { result } = renderHook(() => usePanels("user-1", calc), {
      wrapper: createWrapper("/erp/calc"),
    });
    expect(result.current.menuOpen).toBe(true);
    expect(JSON.parse(window.localStorage.getItem("rt-pf-panels-v2") ?? "{}")).toEqual({
      "user-1|/crm/leads": { lastTab: "history" },
      "user-1|/eds/inbox": { panelMode: "docked" },
      "user-1|*": { menuOpen: true },
      "user-2|*": { menuOpen: false },
    });
    // повторное чтение ничего не меняет
    usePanelsStore.getState().reload();
    expect(usePanelsStore.getState().entries["user-1|*"]).toEqual({ menuOpen: true });
  });

  it("настройки со старого ключа rt-pf-panels-v1 переносятся: подменю и вкладка — да, «открыто» — нет", () => {
    window.localStorage.setItem(
      "rt-pf-panels-v1",
      JSON.stringify({ "user-1|/crm/leads": { menuOpen: false, panelOpen: true, tab: "history" } }),
    );
    usePanelsStore.getState().reload();

    const { result } = renderHook(() => usePanels("user-1", mockSection), {
      wrapper: createWrapper("/crm/leads"),
    });

    expect(result.current.menuOpen).toBe(false);
    expect(result.current.tab).toBe("history");
    expect(result.current.panelOpen).toBe(false);
    expect(window.localStorage.getItem("rt-pf-panels-v1")).toBeNull();
    expect(JSON.parse(window.localStorage.getItem("rt-pf-panels-v2") ?? "{}")).toEqual({
      "user-1|/crm/leads": { lastTab: "history" },
      "user-1|*": { menuOpen: false },
    });
  });

  it("setTab синхронизирует URL query param и сохраняет lastTab в panelsStore", () => {
    const key = panelsKey("user-1", "/crm/leads");
    const locRef = { current: null as Location | null };
    function LocationTracker() {
      locRef.current = useLocation();
      return null;
    }

    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <MemoryRouter initialEntries={["/crm/leads?panel=open"]}>
          <LocationTracker />
          {children}
        </MemoryRouter>
      );
    }

    const { result } = renderHook(() => usePanels("user-1", mockSection), { wrapper: Wrapper });

    expect(result.current.tab).toBe("card");

    act(() => {
      result.current.setTab("tasks");
    });

    expect(result.current.tab).toBe("tasks");
    expect(locRef.current?.search).toContain("tab=tasks");
    expect(usePanelsStore.getState().entries[key]?.lastTab).toBe("tasks");
  });
});
