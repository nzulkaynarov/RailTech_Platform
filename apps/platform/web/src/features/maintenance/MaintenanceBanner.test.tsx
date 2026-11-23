import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../shared/i18n";
import { MaintenanceBanner } from "./MaintenanceBanner";

const STARTS = Date.parse("2026-11-23T19:15:00+05:00");
const MIN = 60_000;
let body: unknown;
let status = 200;

function renderBanner() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <I18nextProvider i18n={i18n}>
        <MaintenanceBanner />
      </I18nextProvider>
    </QueryClientProvider>,
  );
}

beforeEach(async () => {
  await i18n.changeLanguage("ru");
  vi.useFakeTimers({ shouldAdvanceTime: true });
  status = 200;
  window.sessionStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(typeof body === "string" ? body : JSON.stringify(body), { status }),
      ),
    ),
  );
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("MaintenanceBanner", () => {
  it("за 30 минут — предупреждение с временем, role=status", async () => {
    vi.setSystemTime(STARTS - 30 * MIN);
    body = { starts_at: "2026-11-23T19:15:00+05:00", minutes: 3, kind: "planned" };
    renderBanner();
    const banner = await screen.findByRole("status");
    expect(banner.textContent).toContain(
      "Обновление Платформы в 19:15 — работа прервётся на 2–3 минуты. Сохраните изменения.",
    );
  });

  it("срочное исправление — другое слово", async () => {
    vi.setSystemTime(STARTS - 10 * MIN);
    body = { starts_at: "2026-11-23T19:15:00+05:00", kind: "urgent" };
    renderBanner();
    expect((await screen.findByRole("status")).textContent).toContain(
      "Срочное исправление Платформы в 19:15",
    );
  });

  it("внутри работ — «Идёт обновление», кнопки скрытия нет", async () => {
    vi.setSystemTime(STARTS + MIN);
    body = { starts_at: "2026-11-23T19:15:00+05:00", minutes: 3 };
    renderBanner();
    const banner = await screen.findByRole("status");
    expect(banner.textContent).toContain(
      "Идёт обновление — через пару минут страница обновится сама.",
    );
    expect(screen.queryByRole("button", { name: "Скрыть" })).toBeNull();
  });

  it("скрыть: баннер уходит, через 10 минут возвращается", async () => {
    vi.setSystemTime(STARTS - 29 * MIN);
    body = { starts_at: "2026-11-23T19:15:00+05:00", minutes: 3 };
    renderBanner();
    await screen.findByRole("status");
    fireEvent.click(screen.getByRole("button", { name: "Скрыть" }));
    expect(screen.queryByRole("status")).toBeNull();
    await act(async () => {
      vi.setSystemTime(STARTS - 18 * MIN);
      await vi.advanceTimersByTimeAsync(16_000);
    });
    expect(screen.queryByRole("status")).not.toBeNull();
  });

  it("нет файла, мусор и не-JSON — баннера нет", async () => {
    vi.setSystemTime(STARTS - 10 * MIN);
    for (const [s, b] of [
      [404, ""],
      [200, "{}"],
      [200, "<!doctype html><html></html>"],
    ] as const) {
      status = s;
      body = b;
      const view = renderBanner();
      await waitFor(() => {
        expect(fetch).toHaveBeenCalled();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(50);
      });
      expect(screen.queryByRole("status")).toBeNull();
      view.unmount();
    }
  });

  it("не опрашивает, пока вкладка скрыта", async () => {
    vi.setSystemTime(STARTS - 10 * MIN);
    body = {};
    renderBanner();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(1);
    });
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    Object.defineProperty(document, "hidden", { value: true, configurable: true });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(130_000);
    });
    expect(fetch).toHaveBeenCalledTimes(1);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
  });
});
