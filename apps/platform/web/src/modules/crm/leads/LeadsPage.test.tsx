import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { resetLeads } from "../../../mocks/fixtures/leads";
import { resetMessages } from "../../../mocks/fixtures/messages";
import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";

setupBotTests();

beforeEach(() => {
  resetLeads();
  resetMessages();
});

async function open(email: string, path = "/crm/leads") {
  signIn(email);
  const view = renderAt(path);
  expect(await screen.findByRole("heading", { level: 1, name: "Лиды" })).toBeVisible();
  return view;
}

function table(): HTMLElement {
  return screen.getByRole("table", { name: "Лиды" });
}

function names(): string[] {
  return within(table())
    .getAllByRole("link", { name: /^Открыть карточку/ })
    .map((a) => a.textContent);
}

describe("Клиенты · Лиды (D1-2b)", () => {
  it("вкладки по статусу, «Мои / Просроченные» и канал сужают список", async () => {
    await open("manager@demo.example");
    await screen.findByRole("table", { name: "Лиды" });
    expect(names()).toContain("Азиз Демо");
    expect(names()).toContain("Отказ Демо");

    fireEvent.click(screen.getByRole("tab", { name: "Просят КП" }));
    await waitFor(() => {
      expect(names().sort()).toEqual(["Азиз Демо", "Шахноза Демо"]);
    });

    fireEvent.click(screen.getByRole("tab", { name: "Все" }));
    fireEvent.click(screen.getByRole("radio", { name: "Мои" }));
    await waitFor(() => {
      expect(names().sort()).toEqual(["Отабек Демо", "Шахноза Демо"]);
    });

    fireEvent.click(screen.getByRole("radio", { name: "Просроченные" }));
    await waitFor(() => {
      expect(names()).toEqual(["Ждёт ответа Демо"]);
    });
    expect(within(table()).getByText("Срок ответа прошёл")).toBeVisible();
  });

  it("смена вкладки и фильтра — прежние строки на месте с признаком загрузки, без скелетона (UX-1c, S8)", async () => {
    await open("manager@demo.example");
    const before = await screen.findByRole("table", { name: "Лиды" });
    const blockBefore = before.closest(".pf-data-block");
    fireEvent.click(screen.getByRole("tab", { name: "Просят КП" }));
    // Та же таблица (не размонтирована), прежние строки, блок помечен «идёт загрузка»
    expect(table()).toBe(before);
    expect(names()).toContain("Отказ Демо");
    expect(before.closest("[aria-busy]")).toHaveAttribute("aria-busy", "true");
    expect(document.querySelector("[data-pf-skeleton]")).toBeNull();
    await waitFor(() => {
      expect(names().sort()).toEqual(["Азиз Демо", "Шахноза Демо"]);
    });
    // С новыми данными таблица строится заново (строки не «едут» на новые места), блок тот же и без признака загрузки
    const block = table().closest(".pf-data-block");
    expect(block).toBe(blockBefore);
    expect(block).not.toHaveAttribute("aria-busy");
    // Одна панель списка под полосой вкладок, связанная с выбранной вкладкой (пустые панели antd скрыты стилем)
    expect(document.getElementById("pf-leads-tabs-body")).toHaveAttribute(
      "aria-labelledby",
      screen.getByRole("tab", { name: "Просят КП" }).id,
    );
  });

  it("канал — из адреса: только лиды с сайта", async () => {
    await open("manager@demo.example", "/crm/leads?channel=web");
    await waitFor(() => {
      expect(names()).toEqual(["Шахноза Демо"]);
    });
  });

  it("действие строки по статусу: «Создать заявку» у «Просит КП», «Забрать» у открытой передачи, карточка у клиента", async () => {
    const { router } = await open("manager@demo.example");
    await screen.findByRole("table", { name: "Лиды" });
    expect(screen.getByRole("link", { name: "Создать заявку для Азиз Демо" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Карточка клиента Бобур Снабженцев" })).toHaveAttribute(
      "href",
      "/crm/clients/3?panel=open&tab=card",
    );
    expect(
      screen.getByRole("link", { name: "Ответить Отабек Демо в «Ждут ответа»" }),
    ).toHaveAttribute("href", "/crm/messages?lead=L-2050");
    // В отказе действий нет
    const lost = within(table()).getByRole("link", { name: "Открыть карточку Отказ Демо" });
    expect(within(lost.closest("tr") as HTMLElement).queryByRole("button")).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Забрать Ждёт ответа Демо в «Ждут ответа»" }),
    );
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/crm/messages");
    });
    expect(router.state.location.search).toBe("?lead=L-2060");
  });

  it("клик по имени — карточка лида в боковом окне: контакты, согласие, факты, сообщения", async () => {
    await open("manager@demo.example", "/crm/leads?lead=L-2041&panel=open&tab=card");
    const panel = await panelEl();
    expect(await within(panel).findByRole("heading", { name: "Азиз Демо" })).toBeVisible();
    expect(within(panel).getByText("@aziz_demo")).toBeVisible();
    expect(within(panel).getByText(/дано в боте/)).toBeVisible();
    expect(within(panel).getAllByText("Рельсы Р65, 40 т").length).toBeGreaterThan(0);
    expect(within(panel).getByRole("list", { name: "Последние сообщения" })).toBeVisible();
    expect(within(panel).getByRole("link", { name: "Создать заявку" })).toHaveAttribute(
      "href",
      "/crm/leads?lead=L-2041&create=1&panel=open&tab=card",
    );
  });

  it("директор (лиды — чтение): ни «Забрать», ни «Ответить»", async () => {
    await open("director@demo.example");
    await screen.findByRole("table", { name: "Лиды" });
    expect(screen.queryByRole("button", { name: /^Забрать/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /^Ответить/ })).toBeNull();
  });
});
