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

  it("setEntityId устанавливает entityId и открывает панель, а передача null удаляет entityId", () => {
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

    act(() => {
      result.current.setEntityId("lead-401");
    });

    expect(result.current.entityId).toBe("lead-401");
    expect(result.current.panelOpen).toBe(true);
    expect(locRef.current?.search).toContain("entityId=lead-401");
    expect(locRef.current?.search).toContain("panel=open");

    act(() => {
      result.current.setEntityId(null);
    });

    expect(result.current.entityId).toBeNull();
    expect(locRef.current?.search).not.toContain("entityId");
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
