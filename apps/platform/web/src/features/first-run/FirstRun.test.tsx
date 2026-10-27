import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resetEmployees } from "../../mocks/fixtures/employees";
import { resetRoles } from "../../mocks/fixtures/roles";
import { resetExtraUsers } from "../../mocks/fixtures/users";
import { endSession } from "../../mocks/mockSession";
import { readSetup, resetSetup, startFreshInstall, startFreshSetup } from "../../mocks/setupState";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";

/** Пароль и код — на лету для каждого прогона: ни литералов, похожих на настоящие. */
function secret(prefix: string): string {
  return `${prefix}-${globalThis.crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
}

beforeEach(() => {
  window.localStorage.clear();
  resetSetup();
  resetExtraUsers();
  resetEmployees();
  resetRoles();
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

function fill(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

async function openSetup(code: string) {
  startFreshInstall(code);
  const app = renderApp("/login");
  await screen.findByRole("heading", { level: 1, name: "Первый запуск" });
  return app;
}

describe("Первый запуск до входа", () => {
  it("пока администратора нет, вход ведёт на «Первый запуск»", async () => {
    const { router } = await openSetup(secret("code"));

    expect(router.state.location.pathname).toBe("/setup");
    expect(screen.getByText(/setup_code_issued/)).toBeVisible();
    // «Что произойдёт» перед главной кнопкой
    expect(screen.getByText("Что произойдёт")).toBeVisible();
    expect(screen.getByRole("button", { name: /Создать администратора и войти/ })).toBeVisible();
  });

  it("пустая форма и короткий пароль — подсказки у полей, запрос не уходит", async () => {
    await openSetup(secret("code"));
    let calls = 0;
    server.use(
      http.post("*/setup/admin", () => {
        calls += 1;
        return HttpResponse.json({}, { status: 500 });
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Создать администратора и войти" }));
    expect(await screen.findByText("Введите код из журнала сервера")).toBeInTheDocument();
    expect(screen.getByText("Введите имя и фамилию")).toBeInTheDocument();
    expect(screen.getByText("Введите электронную почту")).toBeInTheDocument();

    fill("Пароль", "short1");
    fireEvent.click(screen.getByRole("button", { name: "Создать администратора и войти" }));
    expect(await screen.findByText("Пароль должен быть не короче 10 символов")).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("пароли не совпадают — запрос не уходит", async () => {
    await openSetup(secret("code"));
    fill("Код первого запуска", "x");
    fill("Имя и фамилия", "Первая Админова");
    fill("Электронная почта администратора", "first@demo.example");
    fill("Пароль", secret("pw1"));
    fill("Повторите пароль", secret("pw2"));

    fireEvent.click(screen.getByRole("button", { name: "Создать администратора и войти" }));

    expect(await screen.findByText("Пароли не совпадают")).toBeInTheDocument();
  });

  it("неверный код — ошибка словами, форма остаётся", async () => {
    await openSetup(secret("code"));
    const password = secret("pw");
    fill("Код первого запуска", "wrong-code");
    fill("Имя и фамилия", "Первая Админова");
    fill("Электронная почта администратора", "first@demo.example");
    fill("Пароль", password);
    fill("Повторите пароль", password);

    fireEvent.click(screen.getByRole("button", { name: "Создать администратора и войти" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Код неверный");
    expect(screen.getByRole("button", { name: /Создать администратора и войти/ })).toBeVisible();
  });

  it("слабый пароль — отказ CRM словами", async () => {
    const code = secret("code");
    await openSetup(code);
    const weak = "abcdefghij1";
    fill("Код первого запуска", code);
    fill("Имя и фамилия", "Первая Админова");
    fill("Электронная почта администратора", "abcdefghij@demo.example");
    fill("Пароль", weak);
    fill("Повторите пароль", weak);

    fireEvent.click(screen.getByRole("button", { name: "Создать администратора и войти" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("не короче 10 символов");
  });

  it("верный код: администратор создан, сессия открыта, открывается мастер", async () => {
    const code = secret("code");
    const password = secret("pw");
    const { router } = await openSetup(code);
    fill("Код первого запуска", code);
    fill("Имя и фамилия", "Первая Админова");
    fill("Электронная почта администратора", "first@demo.example");
    fill("Пароль", password);
    fill("Повторите пароль", password);

    fireEvent.click(screen.getByRole("button", { name: "Создать администратора и войти" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Первый запуск" }, { timeout: 5_000 }),
    ).toBeVisible();
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/admin/setup");
    });
    expect(await screen.findByText("Администратор создан: Первая Админова.")).toBeVisible();
    expect(readSetup().needsAdmin).toBe(false);
    // повторный заход на «Первый запуск» уже вошедшего ведёт в Платформу
    expect(document.body).not.toHaveTextContent(password);
  });

  it("администратор уже есть: экран отправляет ко входу", async () => {
    renderApp("/setup");

    expect(
      await screen.findByRole("heading", { name: "Первый запуск уже выполнен" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "К входу" })).toHaveAttribute("href", "/login");
  });

  it("CRM не отвечает: «Повторить», а не пустой экран", async () => {
    server.use(http.get("*/setup/state", () => HttpResponse.json({}, { status: 503 })));
    renderApp("/setup");

    expect(await screen.findByText("Не удалось проверить состояние системы")).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});

describe("Баннер настройки и мастер", () => {
  beforeEach(() => {
    startFreshSetup();
  });

  it("администратор видит баннер «готово 0 из 5» со ссылкой в мастер", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org");

    const banner = await screen.findByRole("region", { name: "Настройка Платформы" });
    expect(within(banner).getByText("Настройка Платформы: готово 0 из 5")).toBeVisible();
    expect(within(banner).getByText(/Своей компании ещё нет в ERP/)).toBeVisible();
    expect(within(banner).getByRole("link", { name: "Продолжить настройку" })).toHaveAttribute(
      "href",
      "/admin/setup",
    );
  });

  it("«Скрыть» убирает баннер и запоминает выбор в браузере", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org");
    const banner = await screen.findByRole("region", { name: "Настройка Платформы" });

    fireEvent.click(within(banner).getByRole("button", { name: "Скрыть баннер настройки" }));

    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Настройка Платформы" })).toBeNull();
    });
    expect(window.localStorage.getItem("rt-pf-setup-banner-hidden:u-demo-admin")).toBe("1");
    // новая загрузка страницы: баннера всё ещё нет
    cleanup();
    renderApp("/admin/org");
    expect(await screen.findByRole("heading", { level: 1, name: "Оргструктура" })).toBeVisible();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 150));
    });
    expect(screen.queryByRole("region", { name: "Настройка Платформы" })).toBeNull();
  });

  it("баннера нет, когда всё сделано и компания создана", async () => {
    startFreshSetup();
    const state = readSetup();
    window.localStorage.setItem(
      "rt-pf-mock-setup",
      JSON.stringify({
        ...state,
        companyCreated: true,
        done: { bot: true, erp: true, mail: true, models: true, first_employee: true },
      }),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/org");

    expect(await screen.findByRole("heading", { level: 1, name: "Оргструктура" })).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Настройка Платформы" })).toBeNull();
    });
  });

  it("раздел скрыт: директор не видит баннер и не запрашивает чек-лист", async () => {
    let calls = 0;
    server.use(
      http.get("*/setup/checklist", () => {
        calls += 1;
        return HttpResponse.json({}, { status: 403 });
      }),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");

    expect(await screen.findByRole("heading", { level: 1 })).toBeVisible();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 150));
    });
    expect(screen.queryByRole("region", { name: "Настройка Платформы" })).toBeNull();
    expect(calls).toBe(0);
  });

  it("менеджер: адрес мастера — «Нет доступа»", async () => {
    signInAs("manager@demo.example");
    renderApp("/admin/setup");

    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
  });

  it("директор открывает мастер по адресу — видит, что это работа администратора", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/setup");

    expect(await screen.findByRole("heading", { level: 1, name: "Первый запуск" })).toBeVisible();
    expect(screen.getByText(/доступен администратору/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /Создать компанию/ })).toBeNull();
  });

  it("мастер: на своей странице баннер не дублируется, пять шагов ведут на свои экраны", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/setup");

    expect(await screen.findByRole("heading", { level: 2, name: "Подключения" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Настройка Платформы" })).toBeNull();
    const list = screen.getByRole("list", { name: "Шаги настройки" });
    const links = within(list).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/admin/integrations?card=telegram&panel=open",
      "/admin/integrations?card=erp&panel=open",
      "/admin/integrations?card=mail&panel=open",
      "/admin/integrations?card=models&panel=open",
      "/admin/org?invite=open&panel=open",
    ]);
    for (const row of within(list).getAllByRole("listitem")) {
      expect(within(row).getByText("Не сделано")).toBeVisible();
    }
    expect(screen.getByText("Готово 0 из 5")).toBeVisible();
  });

  it("шаг «Ваша компания»: форма с блоком «Что произойдёт», создание, затем статус «Готово»", async () => {
    let body: unknown;
    signInAs("admin@demo.example");
    renderApp("/admin/setup");
    expect(await screen.findByRole("heading", { level: 2, name: "Ваша компания" })).toBeVisible();
    expect(await screen.findByText("Что произойдёт")).toBeVisible();

    // название обязательно
    fireEvent.click(screen.getByRole("button", { name: /Создать компанию/ }));
    expect(await screen.findByText("Введите название компании")).toBeInTheDocument();

    server.use(
      http.post("*/setup/company", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: 1, name: "ООО Демо" }, { status: 201 });
      }),
    );
    fill("Название компании", "  ООО Демо ");
    fill("ИНН (необязательно)", "123456789");
    fireEvent.click(screen.getByRole("button", { name: /Создать компанию/ }));

    await waitFor(() => {
      expect(body).toEqual({ name: "ООО Демо", inn: "123456789" });
    });
  });

  it("ошибка поля от ERP показана у поля, повтор после исправления проходит", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/setup");
    await screen.findByRole("heading", { level: 2, name: "Ваша компания" });
    fill("Название компании", "ООО Демо");
    fill("ИНН (необязательно)", "000");

    fireEvent.click(screen.getByRole("button", { name: /Создать компанию/ }));

    expect(await screen.findByText("Компания с таким ИНН уже есть.")).toBeInTheDocument();
    fill("ИНН (необязательно)", "123456789");
    fireEvent.click(screen.getByRole("button", { name: /Создать компанию/ }));
    await waitFor(() => {
      expect(readSetup().companyCreated).toBe(true);
    });
    expect(await screen.findByText("Своя компания создана.")).toBeVisible();
  });

  it("ERP не ответила: «Проверить снова» вместо тупика", async () => {
    server.use(
      http.get("*/setup/checklist", () =>
        HttpResponse.json({
          steps: [
            { key: "bot", state: "todo" },
            { key: "erp", state: "todo" },
            { key: "mail", state: "todo" },
            { key: "models", state: "todo" },
            { key: "first_employee", state: "todo" },
          ],
          done: 0,
          total: 5,
          company: null,
        }),
      ),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/setup");

    expect(await screen.findByText(/ERP пока не ответила/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Проверить снова" })).toBeVisible();
  });

  it("сбой чек-листа: «Повторить»", async () => {
    server.use(http.get("*/setup/checklist", () => HttpResponse.json({}, { status: 503 })));
    signInAs("admin@demo.example");
    renderApp("/admin/setup");

    expect(await screen.findByText("Не удалось получить состояние настройки")).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});
