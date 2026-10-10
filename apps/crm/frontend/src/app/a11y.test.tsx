import { act, render, screen, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppTitle } from "./AppTitle";
import { ConnectionStatus } from "./Header";
import { ensureLiveRegion } from "./liveRegion";
import { NotFound } from "./RouteGuard";

describe("ConnectionStatus", () => {
  it.each([
    [true, "Онлайн"],
    [false, "Нет связи"],
  ])("live=%s → %s as text in a status region", (live, text) => {
    render(<ConnectionStatus live={live} />);
    expect(within(screen.getByRole("status")).getByText(text)).toBeInTheDocument();
  });
});

describe("live region for toasts", () => {
  it("is a single polite status region", () => {
    const region = ensureLiveRegion();
    expect(ensureLiveRegion()).toBe(region);
    expect(region).toHaveAttribute("role", "status");
    expect(region).toHaveAttribute("aria-live", "polite");
  });

  it("receives antd messages", async () => {
    let api: ReturnType<typeof AntApp.useApp> | undefined;
    function Grab() {
      api = AntApp.useApp();
      return null;
    }
    render(
      <AntApp message={{ getContainer: ensureLiveRegion }}>
        <Grab />
      </AntApp>,
    );
    act(() => {
      void api?.message.success("Сохранено");
    });
    expect(await within(ensureLiveRegion()).findByText("Сохранено")).toBeInTheDocument();
  });
});

describe("structure", () => {
  it("sidebar logo is a link, not a heading", () => {
    render(
      <MemoryRouter>
        <AppTitle collapsed={false} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "RailTech CRM" })).toBeInTheDocument();
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("unknown address has its own 404 text", () => {
    render(
      <MemoryRouter>
        <NotFound />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Страница не найдена" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Запись удалена/)).toBeNull();
  });
});
