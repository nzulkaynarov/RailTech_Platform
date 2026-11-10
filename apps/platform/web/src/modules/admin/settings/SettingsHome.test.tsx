import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { endSession } from "../../../mocks/mockSession";
import { renderAt, setupBotTests, signIn } from "../../../test/botKit";

setupBotTests();

async function openHome(email: string, path = "/admin") {
  signIn(email);
  const view = renderAt(path);
  expect(await screen.findByRole("heading", { level: 1, name: "Все настройки" })).toBeVisible();
  return view;
}

const groupTitles = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);

function cardsOf(group: string): string[] {
  const section = screen.getByRole("region", { name: group });
  return within(section)
    .getAllByRole("link")
    .map((link) => link.querySelector(".pf-set-tile-title")?.textContent ?? "");
}

describe("Настройки · индекс «Все настройки» (SET-IA)", () => {
  it("администратор: четыре группы карточек в порядке задачи, у каждой карточки — строка описания", async () => {
    await openHome("admin@demo.example");
    await screen.findByRole("region", { name: "Журнал" });
    expect(groupTitles()).toEqual(
      expect.arrayContaining(["Сотрудники", "Компания", "Подключения", "Журнал"]),
    );
    expect(cardsOf("Сотрудники")).toEqual(["Сотрудники", "Роли и права", "Права подписи"]);
    expect(cardsOf("Подключения")).toEqual([
      "Telegram",
      "Почта",
      "Формы сайта",
      "Подключения",
      "Расходы на ИИ",
    ]);
    expect(cardsOf("Журнал")).toContain("Обмен между системами");
    const mail = within(screen.getByRole("region", { name: "Подключения" })).getByRole("link", {
      name: /Почта/,
    });
    expect(mail).toHaveAttribute("href", "/admin/mail");
    expect(mail).toHaveAccessibleDescription("Отправка писем и приём в общий ящик");
  });

  it("плашки состояния — из обзора подключений: у Telegram и Почты есть, у Сотрудников нет", async () => {
    await openHome("admin@demo.example");
    const channels = await screen.findByRole("region", { name: "Подключения" });
    await waitFor(() => {
      expect(
        within(within(channels).getByRole("link", { name: /Почта/ })).getByText(
          /Работает|Внимание|Сбой|Нет данных/,
        ),
      ).toBeVisible();
    });
    const people = screen.getByRole("region", { name: "Сотрудники" });
    expect(within(people).queryByText(/Работает|Нет данных/)).toBeNull();
  });

  it("поиск «почта»: карточки фильтруются на месте, переход — на страницу «Почта»", async () => {
    const { router } = await openHome("admin@demo.example");
    const search = screen.getByRole("searchbox", { name: "Найти настройку" });
    fireEvent.change(search, { target: { value: "почта" } });
    const results = await screen.findByRole("region", { name: "Найденные настройки" });
    const links = within(results).getAllByRole("link");
    expect(links[0]).toHaveTextContent("Почта");
    expect(screen.queryByRole("region", { name: "Сотрудники" })).toBeNull();
    fireEvent.click(links[0] as HTMLElement);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/admin/mail");
    });
  });

  it("поиск по слову внутри страницы подписывает, чем нашлось; пустой итог — с «Очистить поиск»", async () => {
    await openHome("admin@demo.example");
    const search = screen.getByRole("searchbox", { name: "Найти настройку" });
    fireEvent.change(search, { target: { value: "sla" } });
    const results = await screen.findByRole("region", { name: "Найденные настройки" });
    expect(within(results).getByRole("link", { name: /Время и сроки/ })).toHaveTextContent(
      "Нашлось по слову «sla»",
    );

    fireEvent.change(search, { target: { value: "абракадабра" } });
    expect(await screen.findByText("По запросу «абракадабра» настроек нет.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Очистить поиск" }));
    expect(await screen.findByRole("region", { name: "Сотрудники" })).toBeVisible();
  });

  it("чек-лист «Первый запуск» на свежей установке: число шагов из данных, несделанный шаг — ссылка в мастер", async () => {
    window.localStorage.setItem(
      "rt-pf-mock-setup",
      JSON.stringify({
        needsAdmin: false,
        code: "",
        fresh: true,
        companyCreated: true,
        done: { erp: true },
      }),
    );
    await openHome("admin@demo.example");
    const checklist = await screen.findByRole("region", { name: "Первый запуск: готово 1 из 5" });
    const steps = within(checklist).getByRole("list", { name: "Шаги настройки" });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(5);
    expect(within(steps).getByText("ERP").closest("li")).toHaveTextContent("Готово");
    expect(within(steps).getByRole("link", { name: "Почта" })).toHaveAttribute(
      "href",
      "/admin/setup?step=mail&panel=open",
    );
    expect(within(checklist).getByRole("link", { name: "Продолжить настройку" })).toHaveAttribute(
      "href",
      "/admin/setup",
    );
  });

  it("⚙ из модуля (`?group=`): только своя группа и ссылка «Все группы настроек»", async () => {
    await openHome("admin@demo.example", "/admin?group=company");
    expect(await screen.findByRole("region", { name: "Компания" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Сотрудники" })).toBeNull();
    expect(screen.queryByRole("region", { name: /^Первый запуск/ })).toBeNull();
    expect(screen.getByRole("link", { name: "Все группы настроек" })).toHaveAttribute(
      "href",
      "/admin",
    );
  });

  it("директор: те же группы на чтение, без «Обмена между системами» и без чек-листа первого запуска", async () => {
    await openHome("director@demo.example");
    await screen.findByRole("region", { name: "Журнал" });
    expect(cardsOf("Журнал")).not.toContain("Обмен между системами");
    expect(screen.queryByRole("region", { name: /^Первый запуск/ })).toBeNull();
    const search = screen.getByRole("searchbox", { name: "Найти настройку" });
    fireEvent.change(search, { target: { value: "обмен" } });
    expect(await screen.findByText("По запросу «обмен» настроек нет.")).toBeVisible();
  });

  it("подменю Настроек — четыре группы с заголовками; без «Первого запуска» и «Обращений сотрудников»", async () => {
    await openHome("admin@demo.example");
    const menu = screen.getByRole("navigation", { name: "Разделы модуля" });
    const groups = within(menu)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(groups).toEqual(["Сотрудники", "Компания", "Подключения", "Журнал"]);
    expect(within(menu).queryByRole("link", { name: "Первый запуск" })).toBeNull();
    expect(within(menu).queryByRole("link", { name: "Обращения сотрудников" })).toBeNull();
  });

  it("⚙ в заголовке подменю «Документов» ведёт в группу «Процессы»; у менеджера без Настроек значка нет", async () => {
    signIn("admin@demo.example");
    renderAt("/eds/documents");
    const gear = await screen.findByRole("link", { name: "Настройки: Компания" });
    expect(gear).toHaveAttribute("href", "/admin?group=company");
    cleanup();
    endSession();

    signIn("manager@demo.example");
    renderAt("/eds/documents");
    await screen.findByRole("navigation", { name: "Разделы модуля" });
    expect(screen.queryByRole("link", { name: /^Настройки: / })).toBeNull();
  });
});
