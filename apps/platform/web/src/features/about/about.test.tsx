import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { endSession } from "../../mocks/mockSession";
import type { Me } from "../../shared/api/generated/model";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { setViewportWidth } from "../../test/viewport";
import { browserOf, releaseText, supportText } from "./release";

const t = i18n.t.bind(i18n);

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  cleanup();
  endSession();
  vi.restoreAllMocks();
});

describe("версия Платформы (W-REL)", () => {
  it("«Платформа ГГГГ.ММ.ДД · sha»; без sha — только дата; локальная сборка — словами", () => {
    expect(releaseText(t, { version: "2026.10.28", sha: "1a2b3c4" })).toBe(
      "Платформа 2026.10.28 · 1a2b3c4",
    );
    expect(releaseText(t, { version: "2026.10.28" })).toBe("Платформа 2026.10.28");
    expect(releaseText(t, { version: "dev" })).toBe("Платформа · локальная сборка");
    expect(releaseText(t, undefined)).toBeUndefined();
  });

  it("браузер — семейство и мажорная версия, без отпечатка устройства", () => {
    expect(
      browserOf(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.86 Safari/537.36",
      ),
    ).toBe("Chrome 131 · macOS");
    expect(
      browserOf(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
      ),
    ).toBe("Safari 18 · iOS");
    expect(
      browserOf("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"),
    ).toBe("Firefox 132 · Windows");
    expect(browserOf("curl/8")).toBe("—");
  });

  it("данные для поддержки: версия, роль, язык, браузер, экран, время — без имени и почты", () => {
    const me = {
      id: "7",
      name: "Иван Тестов",
      email: "ivan.test@example.org",
      initials: "ИТ",
      language: "ru",
      roles: [{ id: "3", name: "Менеджер", system: false }],
    } as unknown as Me;
    const text = supportText(t, {
      me,
      release: { version: "2026.10.28", sha: "1a2b3c4" },
      userAgent: "Mozilla/5.0 (X11; Linux x86_64) Chrome/131.0 Safari/537.36",
      screen: { width: 1440, height: 900 },
      now: new Date("2026-10-28T09:00:00Z"),
    });
    expect(text).toBe(
      [
        "Версия: Платформа 2026.10.28 · 1a2b3c4",
        "Роль: Менеджер",
        "Язык: ru",
        "Браузер: Chrome 131 · Linux",
        "Экран: 1440×900",
        "Время: 2026-10-28T09:00:00.000Z",
      ].join("\n"),
    );
    expect(text).not.toContain("Иван");
    expect(text).not.toContain("@");
  });
});

describe("«Помощь → О системе» (W-REL)", () => {
  it("версия, дата обновления, сервисы словом и копирование данных для поддержки", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    signInAs("manager@demo.example");
    renderApp("/help/about");

    expect(await screen.findByText("Платформа 2026.10.28 · 1a2b3c4")).toBeInTheDocument();
    expect(screen.getByText(/^Обновлена/)).toBeInTheDocument();
    const services = screen.getByRole("list", { name: "Сервисы" });
    expect(within(services).getAllByRole("listitem")).toHaveLength(4);
    expect(within(services).getByText("Документы (EDS)")).toBeInTheDocument();
    expect(within(services).getAllByText("Работает")).toHaveLength(4);
    expect(within(services).getAllByText("версию не сообщает")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Скопировать данные для поддержки" }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledTimes(1);
    });
    const copied = String((writeText.mock.calls[0] as unknown[])[0]);
    expect(copied).toContain("Версия: Платформа 2026.10.28 · 1a2b3c4");
    expect(copied).toContain("Роль: Менеджер");
    expect(copied).not.toContain("manager@demo.example");
    expect(await screen.findByText(/^Скопировано/)).toBeInTheDocument();
  });

  it("браузер не дал скопировать — честная подсказка, текст на экране", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: () => Promise.reject(new Error("denied")) },
      configurable: true,
    });
    signInAs("manager@demo.example");
    renderApp("/help/about");
    fireEvent.click(
      await screen.findByRole("button", { name: "Скопировать данные для поддержки" }),
    );
    expect(await screen.findByText(/Браузер не дал скопировать/)).toBeInTheDocument();
    expect(screen.getByText(/Версия: Платформа/)).toBeInTheDocument();
  });

  it("внизу меню аватара — версия; пункт ведёт в «О системе»", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    fireEvent.click(await screen.findByRole("button", { name: /профиль и настройки/ }));
    const item = await screen.findByRole("menuitem", { name: /О системе/ });
    await waitFor(() => {
      expect(item).toHaveTextContent("Платформа 2026.10.28 · 1a2b3c4");
    });
    fireEvent.click(item);
    expect(await screen.findByRole("heading", { name: "О системе", level: 2 })).toBeInTheDocument();
  });
});
