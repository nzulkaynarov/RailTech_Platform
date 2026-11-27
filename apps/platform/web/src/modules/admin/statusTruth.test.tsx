import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { resetFeedMocks } from "../../mocks/feedHandlers";
import { endSession } from "../../mocks/mockSession";
import {
  UNKNOWN,
  WORKS,
  crmDownHandlers,
  crmPartialHandlers,
  overviewWith,
} from "../../mocks/statusScenarios";
import { resetTicketsMock } from "../../mocks/ticketsStore";
import type { StatusFact, StatusState } from "../../shared/api/generated/model";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";

/**
 * «Правда о состоянии» (НАСТ-П1, аудит Настроек §7, сторож 3 и 4): один факт — один ответ на «Состоянии», в «Сервисах»
 * и в мастере; CRM не отвечает или отвечает частично — на экранах нет «Работает», «Всё в порядке» и «Готово» там,
 * где проверить не удалось.
 */

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
  resetFeedMocks();
  resetTicketsMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

const fact = (state: StatusState): StatusFact => ({ ...WORKS, state, live: state === "works" });

const WORDS: readonly [StatusState, string][] = [
  ["works", "Работает"],
  ["stale", "Нет свежих данных"],
  ["not_verified", "Настроено, не проверено"],
  ["unknown", "Не удалось проверить"],
  ["attention", "Внимание"],
  ["broken", "Сбой"],
];

const tag = (scope: HTMLElement) => scope.querySelector<HTMLElement>(".ant-tag")?.textContent;

describe("один факт — один ответ", () => {
  it.each(WORDS)(
    "почта «%s»: строка «Состояния», карточка «Сервисов» и шаг мастера говорят одно слово",
    async (state, word) => {
      server.use(
        http.get("*/admin/integrations", () =>
          HttpResponse.json(overviewWith({ mail: fact(state) })),
        ),
      );

      signInAs("admin@demo.example");
      renderApp("/admin");
      const services = await screen.findByRole("region", { name: "Службы" });
      const mailRow = () => services.querySelector<HTMLElement>('[data-service="mail"]');
      await waitFor(() => {
        expect(tag(mailRow() as HTMLElement)).toBe(word);
      });
      const onState = tag(mailRow() as HTMLElement);
      cleanup();

      renderApp("/admin/integrations");
      const tile = await waitFor(() => {
        const found = document.querySelector<HTMLElement>('article[data-card="mail"]');
        if (!found) throw new Error("нет карточки");
        return found;
      });
      const onServices = tag(tile);
      cleanup();

      renderApp("/admin/setup");
      const step = await waitFor(() => {
        const found = document.querySelector<HTMLElement>('li[data-step="mail"]');
        if (!found) throw new Error("нет шага");
        return found;
      });
      const onWizard = tag(step);

      expect([onState, onServices, onWizard]).toEqual([word, word, word]);
    },
  );

  it("счётчик готовности один: шаг службы не «Работает» — не засчитан ни в «Состоянии», ни в мастере", async () => {
    server.use(
      http.get("*/admin/integrations", () =>
        HttpResponse.json(overviewWith({ mail: fact("stale") })),
      ),
    );
    signInAs("admin@demo.example");
    renderApp("/admin");
    const ready = await screen.findByRole("region", { name: /^Готовность · \d+ из \d+$/ });
    const name = within(ready).getByRole("heading", { level: 2 }).textContent;
    const onState = /Готовность · (\d+) из (\d+)/.exec(name);
    cleanup();

    renderApp("/admin/setup");
    const subtitle = (await screen.findAllByText(/готово \d+ из \d+/i))[0] as HTMLElement;
    const onWizard = /(\d+) из (\d+)/.exec(subtitle.textContent);

    expect(onState?.[1]).toBe(onWizard?.[1]);
    expect(onState?.[2]).toBe(onWizard?.[2]);
    // 9 из 10 → с неготовой почтой на один меньше: почта «Нет свежих данных» не засчитана
    expect(name).not.toMatch(/(\d+) из \1$/);
  });
});

const FORBIDDEN = [/Работает(?! с перебоями)/, /Всё в порядке/, /Готово/, /Проблем не найдено\.$/];

function expectNone(scope: HTMLElement) {
  for (const pattern of FORBIDDEN) {
    expect(within(scope).queryByText(pattern), String(pattern)).toBeNull();
  }
}

describe("CRM не отвечает", () => {
  it("«Состояние»: ни «Работает», ни «Проблем не найдено» — строка «Не удалось проверить» и слова у каждой службы", async () => {
    server.use(...crmDownHandlers);
    signInAs("admin@demo.example");
    renderApp("/admin");

    const attention = await screen.findByRole("region", { name: /^Требует внимания · \d+$/ });
    expect(await within(attention).findByText(/Не удалось проверить: .*службы/)).toBeVisible();
    expect(within(attention).queryByText(/Проблем не найдено/)).toBeNull();
    const services = await screen.findByRole("region", { name: "Службы" });
    await waitFor(() => {
      expect(within(services).getAllByText("Не удалось проверить").length).toBeGreaterThanOrEqual(
        5,
      );
    });
    expectNone(services);
    expectNone(attention);
  });

  it("«Сервисы»: понятная ошибка и «Повторить», карточек со словом «Работает» нет", async () => {
    server.use(...crmDownHandlers);
    signInAs("admin@demo.example");
    renderApp("/admin/integrations");

    expect(await screen.findByRole("button", { name: "Повторить" })).toBeVisible();
    expect(document.querySelector("article[data-card]")).toBeNull();
    expectNone(document.body);
  });

  it("«Первый запуск»: чек-лист не пришёл — ошибка и «Повторить», ни одного «Готово»", async () => {
    server.use(...crmDownHandlers);
    signInAs("admin@demo.example");
    renderApp("/admin/setup");

    expect(await screen.findByRole("button", { name: "Повторить" })).toBeVisible();
    expectNone(document.body);
  });
});

describe("CRM отвечает частично", () => {
  it("«Состояние»: у не проверенных служб — «Не удалось проверить», строки в «Требует внимания», шина — тоже", async () => {
    server.use(...crmPartialHandlers);
    signInAs("admin@demo.example");
    renderApp("/admin");

    const attention = await screen.findByRole("region", { name: /^Требует внимания · \d+$/ });
    expect(await within(attention).findAllByText("Модели ИИ")).not.toHaveLength(0);
    expect(within(attention).queryByText(/Проблем не найдено/)).toBeNull();
    const services = await screen.findByRole("region", { name: "Службы" });
    await waitFor(() => {
      for (const key of ["erp", "backups", "ai", "bus"]) {
        const row = services.querySelector<HTMLElement>(`[data-service="${key}"]`);
        expect(row, key).not.toBeNull();
        expect(tag(row as HTMLElement), key).toBe("Не удалось проверить");
      }
    });
    const mail = services.querySelector<HTMLElement>('[data-service="mail"]') as HTMLElement;
    expect(tag(mail)).toBe("Нет свежих данных");
    for (const key of ["erp", "backups", "ai", "bus", "mail"]) {
      const row = services.querySelector<HTMLElement>(`[data-service="${key}"]`) as HTMLElement;
      expect(row.textContent, key).not.toMatch(/Работает|Всё в порядке|Готово/);
    }
  });

  it("«Сервисы»: у карточек без ответа — «Не удалось проверить» и никогда «Всё в порядке»", async () => {
    server.use(...crmPartialHandlers);
    signInAs("admin@demo.example");
    renderApp("/admin/integrations");

    for (const key of ["erp", "models", "storage"]) {
      const tile = await waitFor(() => {
        const found = document.querySelector<HTMLElement>(`article[data-card="${key}"]`);
        if (!found) throw new Error("нет карточки");
        return found;
      });
      expect(tag(tile), key).toBe("Не удалось проверить");
      expect(within(tile).queryByText(/Всё в порядке|Работает/), key).toBeNull();
    }
  });

  it("«Первый запуск»: шаги служб без подтверждённой проверки не «Готово»", async () => {
    server.use(...crmPartialHandlers);
    signInAs("admin@demo.example");
    renderApp("/admin/setup");

    for (const key of ["mail", "models"]) {
      const step = await waitFor(() => {
        const found = document.querySelector<HTMLElement>(`li[data-step="${key}"]`);
        if (!found) throw new Error("нет шага");
        return found;
      });
      expect(step.textContent, key).not.toMatch(/Готово|Работает/);
    }
    expect(screen.queryByText(/Всё готово/)).toBeNull();
  });

  it("сценарий достижим: «Не удалось проверить» у UNKNOWN — то же слово, что в ответе BFF", () => {
    expect(UNKNOWN.state).toBe("unknown");
  });
});
