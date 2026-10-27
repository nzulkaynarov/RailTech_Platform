import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePanelsStore } from "../app/shell/panelsStore";
import { endSession } from "../mocks/mockSession";
import { setBridgeMock } from "../mocks/bridgeHandlers";
import i18n from "../shared/i18n";
import { renderApp, signInAs } from "../test/renderApp";
import { setViewportWidth } from "../test/viewport";
import { objectTitle } from "./bridge";

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  cleanup();
  endSession();
  setBridgeMock(null);
  vi.restoreAllMocks();
});

async function main() {
  await screen.findByRole("heading", { level: 1 });
  return screen.getByRole("main");
}

describe("SectionStubPage · раздел с мостом", () => {
  it("менеджер, Все сообщения: заголовок, где делается работа, кнопка в новую вкладку, когда появится", async () => {
    signInAs("manager@demo.example");
    renderApp("/crm/messages");
    const page = await main();

    expect(within(page).getByRole("heading", { level: 1, name: "Все сообщения" })).toBeVisible();
    expect(
      within(page).getByRole("heading", {
        level: 2,
        name: "Этот раздел ещё переносится в Платформу",
      }),
    ).toBeVisible();
    expect(
      within(page).getByText(
        "Сейчас эта работа делается в старой CRM: раздел «Входящие». Данные не потеряны.",
      ),
    ).toBeVisible();

    const open = await within(page).findByRole("link", { name: /Открыть в старой CRM/ });
    expect(open).toHaveAttribute("href", "http://crm.localhost:8088/inbox");
    expect(open).toHaveAttribute("target", "_blank");
    expect(open.getAttribute("rel")).toContain("noopener");
    expect(within(page).getByText("Может попросить войти тем же логином.")).toBeVisible();
    expect(within(page).getByText("Когда появится: в ближайшем обновлении.")).toBeVisible();
  });

  it("ни «пока нет», ни «фаза Pn» нет ни на одной заглушке", async () => {
    signInAs("all@demo.example");
    for (const path of [
      "/crm/messages",
      "/crm/leads",
      "/crm/clients",
      "/eds/inbox",
      "/eds/payments",
      "/erp/calc",
      "/chats",
      "/admin/tickets",
    ]) {
      renderApp(path);
      await main();
      const text = document.body.textContent;
      expect(text, path).not.toMatch(/пока нет|пока пуст|фазе P\d|Заявок нет/i);
      expect(text, path).toContain("Когда появится");
      cleanup();
    }
  });

  it("ERP: ссылка ведёт на хэш-маршрут старого ERP, под кнопкой — путь после входа", async () => {
    signInAs("supply@demo.example");
    renderApp("/erp/catalog");
    const page = await main();
    const open = await within(page).findByRole("link", { name: /Открыть в старом ERP/ });
    expect(open).toHaveAttribute("href", "http://erp.localhost:8088/#catalog-reference");
    expect(open).toHaveAttribute("target", "_blank");
    expect(
      within(page).getByText(/Вход выполнится сам\. Старый ERP откроется на главной странице/),
    ).toBeVisible();
    expect(within(page).getByText("Когда появится: к пилоту.")).toBeVisible();
  });

  it("ERP: клик берёт одноразовый SSO-адрес у BFF и открывает его в новой вкладке", async () => {
    signInAs("supply@demo.example");
    renderApp("/erp/catalog");
    const open = await screen.findByRole("link", { name: /Открыть в старом ERP/ });
    const replace = vi.fn();
    const tab = { opener: {}, location: { replace } };
    const openWindow = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    fireEvent.click(open);

    expect(openWindow).toHaveBeenCalledWith("about:blank", "_blank");
    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith(
        "http://erp.localhost:8088/sso/exchange#token=mock-one-time-token",
      );
    });
    expect(tab.opener).toBeNull();
  });

  it("ERP: SSO не вышел — вкладка получает обычную ссылку, под кнопкой честное пояснение", async () => {
    setBridgeMock({ ssoFails: true });
    signInAs("supply@demo.example");
    renderApp("/erp/catalog");
    const open = await screen.findByRole("link", { name: /Открыть в старом ERP/ });
    const replace = vi.fn();
    vi.spyOn(window, "open").mockReturnValue({
      opener: {},
      location: { replace },
    } as unknown as Window);

    fireEvent.click(open);

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith("http://erp.localhost:8088/#catalog-reference");
    });
    expect(await screen.findByText(/Вход без второго пароля не получился/)).toBeVisible();
  });

  it("всплывающие окна закрыты — срабатывает обычная ссылка, запросов SSO нет", async () => {
    signInAs("supply@demo.example");
    renderApp("/erp/catalog");
    const open = await screen.findByRole("link", { name: /Открыть в старом ERP/ });
    vi.spyOn(window, "open").mockReturnValue(null);
    const notPrevented = fireEvent.click(open);
    expect(notPrevented).toBe(true);
  });
});

describe("SectionStubPage · раздел без аналога в старых экранах", () => {
  it("директор, Входящие: честно «в интерфейсе нет», кто делает, когда появится; кнопки нет", async () => {
    signInAs("director@demo.example");
    renderApp("/eds/inbox");
    const page = await main();

    expect(
      within(page).getByText(
        "Сейчас этой работы в интерфейсе нет; её делает директор: резолюции на входящие письма пока даются устно или на бумаге. Данные не потеряны.",
      ),
    ).toBeVisible();
    expect(within(page).queryByRole("link", { name: /Открыть в/ })).not.toBeInTheDocument();
    expect(within(page).queryByRole("button")).not.toBeInTheDocument();
    expect(within(page).getByText("Когда появится: в ближайшем обновлении.")).toBeVisible();
  });
});

describe("SectionStubPage · адрес старой системы не определён", () => {
  it("кнопки нет, текст остаётся честным и подсказывает, у кого спросить", async () => {
    setBridgeMock({ crmUrl: null });
    signInAs("manager@demo.example");
    renderApp("/crm/leads");
    const page = await main();

    expect(
      within(page).getByText(/Сейчас эта работа делается в старой CRM: раздел «Лиды»/),
    ).toBeVisible();
    await waitFor(() => {
      expect(
        within(page).getByText(
          "Адрес не определён: спросите администратора, где открывается старая CRM.",
        ),
      ).toBeVisible();
    });
    expect(within(page).queryByRole("link", { name: /Открыть в/ })).not.toBeInTheDocument();
  });
});

describe("SectionStubPage · карточка объекта по прямой ссылке", () => {
  it("письмо из «Моей очереди»: «Письмо ВХ-104/26», что известно очереди, без «Входящих писем пока нет»", async () => {
    signInAs("director@demo.example");
    renderApp("/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution");
    const page = await main();

    expect(within(page).getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
    const known = await within(page).findByRole("region", {
      name: "Что известно из «Моей очереди»",
    });
    expect(within(known).getByText("Наложить резолюцию на письмо ВХ-104/26")).toBeVisible();
    expect(within(known).getByText(/ООО «Демо-Депо» · заявка ЗВ-2026-104/)).toBeVisible();
    expect(within(known).getByText("срок сегодня")).toBeVisible();
    expect(within(page).queryByText(/Входящих писем пока нет/)).not.toBeInTheDocument();
    expect(document.title).toContain("Письмо ВХ-104/26");
  });

  it("лид по ?lead=: «Лид L-2041», кнопка ведёт прямо в карточку лида старой CRM", async () => {
    signInAs("manager@demo.example");
    renderApp("/crm/leads?lead=L-2041&panel=open&tab=card");
    const page = await main();

    expect(within(page).getByRole("heading", { level: 1, name: "Лид L-2041" })).toBeVisible();
    const open = await within(page).findByRole("link", { name: /Открыть в старой CRM/ });
    expect(open).toHaveAttribute("href", "http://crm.localhost:8088/leads/2041");
    expect(await within(page).findByText("Взять в работу лида L-2041")).toBeVisible();
  });

  it("очередь о нём ничего не знает — только номер и кнопка", async () => {
    signInAs("manager@demo.example");
    renderApp("/crm/leads/L-9999");
    const page = await main();

    expect(within(page).getByRole("heading", { level: 1, name: "Лид L-9999" })).toBeVisible();
    expect(await within(page).findByRole("link", { name: /Открыть в старой CRM/ })).toHaveAttribute(
      "href",
      "http://crm.localhost:8088/leads/9999",
    );
    expect(within(page).queryByRole("region", { name: /Моей очереди/ })).not.toBeInTheDocument();
  });

  it("КП-2026/118 — заголовок без повтора «КП КП-…»", () => {
    expect(objectTitle("КП", "КП-2026/118")).toBe("КП-2026/118");
    expect(objectTitle("Письмо", "ВХ-104/26")).toBe("Письмо ВХ-104/26");
    expect(objectTitle(undefined, "ВХ-104/26")).toBe("ВХ-104/26");
  });
});

describe("Бейджи меню у заглушек", () => {
  it("«Все сообщения»: бейдж 1 только с подсказкой «в старой CRM: 1», а текст раздела не говорит «пока нет»", async () => {
    signInAs("manager@demo.example");
    renderApp("/crm/messages");
    const page = await main();
    const menu = screen.getByRole("navigation", { name: "Разделы модуля" });

    const item = await within(menu).findByRole("link", { name: /Все сообщения.*в старой CRM: 1/ });
    expect(item.querySelector("[title='в старой CRM: 1']")).not.toBeNull();
    expect(within(page).queryByText(/пока нет/)).not.toBeInTheDocument();
  });

  it("раздел без аналога в старых экранах: бейджа нет", async () => {
    signInAs("director@demo.example");
    renderApp("/eds/inbox");
    await main();
    const menu = screen.getByRole("navigation", { name: "Разделы модуля" });
    const item = within(menu).getByRole("link", { name: /Входящие/ });
    expect(item.querySelector(".pf-badge")).toBeNull();
    expect(item).toHaveAccessibleName("Входящие");
  });
});
