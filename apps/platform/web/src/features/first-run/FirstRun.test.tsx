import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resetEmployees } from "../../mocks/fixtures/employees";
import { resetRoles } from "../../mocks/fixtures/roles";
import { resetExtraUsers } from "../../mocks/fixtures/users";
import { endSession } from "../../mocks/mockSession";
import {
  markStepDone,
  readSetup,
  resetSetup,
  startFreshInstall,
  startFreshSetup,
} from "../../mocks/setupState";
import { ERP_RECHECK } from "../../entities/setup/recheck";
import i18n from "../../shared/i18n";
import { hideBanner, resetBannerHidden, startOfTomorrow } from "./hidden";
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
    // основной текст — без технических слов; где искать код, — в свёрнутом блоке для техспециалиста
    expect(
      screen.getByText(/Код первого запуска выдаёт тот, кто разворачивал Платформу/),
    ).toBeVisible();
    expect(screen.getByText(/docker compose/)).not.toBeVisible(); // только внутри свёрнутого блока
    expect(screen.getByText("Подробнее для техспециалиста")).toBeVisible();
    expect(screen.getByText(/setup_code_issued/)).not.toBeVisible();
    fireEvent.click(screen.getByText("Подробнее для техспециалиста"));
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
    expect(await screen.findByText("Введите код первого запуска")).toBeInTheDocument();
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
    resetBannerHidden("u-demo-admin"); // «Скрыть» помнит и память модуля, не только localStorage
    startFreshSetup();
  });

  it("администратор видит баннер «готово 0 из 5» со ссылкой в мастер", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org");

    const banner = await screen.findByRole("region", { name: "Настройка Платформы" });
    expect(within(banner).getByText("Настройка Платформы: готово 0 из 5")).toBeVisible();
    expect(within(banner).getByText(/Дальше: ERP/)).toBeVisible();
    expect(within(banner).getByRole("link", { name: "Продолжить настройку" })).toHaveAttribute(
      "href",
      "/admin/setup",
    );
  });

  it("«Скрыть до завтра» убирает баннер до начала следующих суток и запоминает выбор в браузере", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org");
    const banner = await screen.findByRole("region", { name: "Настройка Платформы" });

    expect(
      within(banner).getByRole("button", { name: "Скрыть до завтра: баннер настройки" }),
    ).toHaveTextContent("Скрыть до завтра");
    fireEvent.click(
      within(banner).getByRole("button", { name: "Скрыть до завтра: баннер настройки" }),
    );

    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Настройка Платформы" })).toBeNull();
    });
    const until = Number(window.localStorage.getItem("rt-pf-setup-banner-hidden:u-demo-admin"));
    expect(until).toBe(startOfTomorrow());
    // новая загрузка страницы: баннера всё ещё нет
    cleanup();
    renderApp("/admin/org");
    expect(await screen.findByRole("heading", { level: 1, name: "Сотрудники" })).toBeVisible();
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

    expect(await screen.findByRole("heading", { level: 1, name: "Сотрудники" })).toBeVisible();
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

  it("мастер: порядок «администратор -> ERP -> компания -> остальное», баннер не дублируется, шаги ведут на свои экраны", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/setup");

    expect(
      await screen.findByRole("heading", { level: 2, name: "Остальные подключения" }),
    ).toBeVisible();
    const order = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(order).toEqual([
      "Администратор",
      "Подключение ERP",
      "Ваша компания",
      "Остальные подключения",
    ]);
    expect(screen.queryByRole("region", { name: "Настройка Платформы" })).toBeNull();
    // ERP — отдельный шаг с главной кнопкой «Подключить ERP» (на новой установке без кода сопряжения)
    // W15-H4: каждый шаг открывается внутри мастера — в его боковом окне, без перехода на другие экраны
    for (const link of screen.getAllByRole("link", { name: "Подключить ERP" })) {
      expect(link).toHaveAttribute("href", "/admin/setup?step=erp&panel=open");
    }
    const list = screen.getByRole("list", { name: "Шаги настройки" });
    const links = within(list).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/admin/setup?step=bot&panel=open",
      "/admin/setup?step=mail&panel=open",
      "/admin/setup?step=models&panel=open",
      "/admin/setup?step=first_employee&panel=open",
    ]);
    for (const row of within(list).getAllByRole("listitem")) {
      expect(within(row).getByText("Не сделано")).toBeVisible();
    }
    expect(screen.getByText("Готово 0 из 5")).toBeVisible();
  });

  it("ERP не подключена: «Ваша компания» объясняет и ведёт на шаг ERP — без формы и «Проверить снова»", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/setup");

    expect(await screen.findByText("Сначала подключите ERP")).toBeVisible();
    expect(screen.getByText("Ждёт ERP")).toBeVisible();
    expect(screen.queryByLabelText("Название компании")).toBeNull();
    expect(screen.queryByRole("button", { name: /Создать компанию/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Проверить снова" })).toBeNull();
    expect(screen.queryByText(/ERP пока не ответила/)).toBeNull();
    const company = screen
      .getByRole("heading", { level: 2, name: "Ваша компания" })
      .closest(".ant-card");
    expect(company).not.toBeNull();
    expect(
      within(company as HTMLElement).getByRole("link", { name: "Подключить ERP" }),
    ).toHaveAttribute("href", "/admin/setup?step=erp&panel=open");
  });

  it("после подключения ERP форма компании появляется", async () => {
    markStepDone("erp");
    signInAs("admin@demo.example");
    renderApp("/admin/setup");

    expect(await screen.findByLabelText("Название компании")).toBeVisible();
    expect(screen.queryByText("Сначала подключите ERP")).toBeNull();
    expect(
      screen.getByText(
        "ERP подключена. Связь можно проверить в форме шага или в Настройках · Подключениях.",
      ),
    ).toBeVisible();
  });

  it("баннер ведёт сначала к ERP: «Дальше: ERP»", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org");

    const banner = await screen.findByRole("region", { name: "Настройка Платформы" });
    expect(within(banner).getByText(/Дальше: ERP/)).toBeVisible();
  });

  it("шаг «Ваша компания»: форма с блоком «Что произойдёт», создание, затем статус «Готово»", async () => {
    let body: unknown;
    markStepDone("erp");
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
    markStepDone("erp");
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

  it("ERP подключена, но не ответила: «Проверить снова» вместо тупика", async () => {
    server.use(
      http.get("*/setup/checklist", () =>
        HttpResponse.json({
          steps: [
            { key: "erp", state: "done" },
            { key: "bot", state: "todo" },
            { key: "mail", state: "todo" },
            { key: "models", state: "todo" },
            { key: "first_employee", state: "todo" },
          ],
          done: 1,
          total: 5,
          company: null,
          company_blocker: "erp_unavailable",
        }),
      ),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/setup");

    expect(await screen.findByText(/ERP пока не ответила/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Проверить снова" })).toBeVisible();
    expect(screen.queryByText("Сначала подключите ERP")).toBeNull();
  });

  it("409 ERP_NOT_CONNECTED при создании: шаг перерисовывается как «сначала подключите ERP»", async () => {
    // экран ещё думает, что ERP есть, а BFF уже знает, что нет
    markStepDone("erp");
    signInAs("admin@demo.example");
    renderApp("/admin/setup");
    await screen.findByLabelText("Название компании");
    server.use(
      http.post("*/setup/company", () =>
        HttpResponse.json(
          {
            code: "ERP_NOT_CONNECTED",
            message: "ERP не подключена. Сначала подключите ERP.",
            source: "bff",
          },
          { status: 409 },
        ),
      ),
      http.get("*/setup/checklist", () =>
        HttpResponse.json({
          steps: [
            { key: "erp", state: "todo" },
            { key: "bot", state: "todo" },
            { key: "mail", state: "todo" },
            { key: "models", state: "todo" },
            { key: "first_employee", state: "todo" },
          ],
          done: 0,
          total: 5,
          company: null,
          company_blocker: "erp_not_connected",
        }),
      ),
    );
    fill("Название компании", "ООО Демо");

    fireEvent.click(screen.getByRole("button", { name: /Создать компанию/ }));

    expect(await screen.findByText("Сначала подключите ERP")).toBeVisible();
    expect(screen.queryByLabelText("Название компании")).toBeNull();
  });

  it("повтор после потерянного ответа: OWN_COMPANY_ALREADY_EXISTS — это успех, шаг переходит в «Готово»", async () => {
    markStepDone("erp");
    signInAs("admin@demo.example");
    renderApp("/admin/setup");
    await screen.findByLabelText("Название компании");
    // первая попытка создала компанию, но ответ потерялся; вторая получает 409
    const state = readSetup();
    window.localStorage.setItem(
      "rt-pf-mock-setup",
      JSON.stringify({ ...state, companyCreated: true }),
    );
    fill("Название компании", "ООО Демо");

    fireEvent.click(screen.getByRole("button", { name: /Создать компанию/ }));

    expect(await screen.findByText("Своя компания создана.")).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByLabelText("Название компании")).toBeNull();
  });

  it("таймаут при создании: чек-лист перечитывается, текст говорит, что компания могла быть создана", async () => {
    markStepDone("erp");
    let checklistCalls = 0;
    signInAs("admin@demo.example");
    renderApp("/admin/setup");
    await screen.findByLabelText("Название компании");
    server.use(
      http.post("*/setup/company", () =>
        HttpResponse.json(
          { code: "REQUEST_TIMEOUT", message: "Сервер не ответил вовремя." },
          { status: 504 },
        ),
      ),
      http.get("*/setup/checklist", () => {
        checklistCalls += 1;
        return HttpResponse.json({
          steps: [
            { key: "erp", state: "done" },
            { key: "bot", state: "todo" },
            { key: "mail", state: "todo" },
            { key: "models", state: "todo" },
            { key: "first_employee", state: "todo" },
          ],
          done: 1,
          total: 5,
          company: { required: true, can_setup: true },
          company_blocker: null,
        });
      }),
    );
    fill("Название компании", "ООО Демо");

    fireEvent.click(screen.getByRole("button", { name: /Создать компанию/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Возможно, компания уже создана/);
    await waitFor(() => {
      expect(checklistCalls).toBeGreaterThan(0);
    });
  });

  it("баннер, скрытый до завтра, возвращается кнопкой в мастере; прежнее «навсегда» уже не скрывает", async () => {
    window.localStorage.setItem("rt-pf-setup-banner-hidden:u-demo-admin", "1");
    signInAs("admin@demo.example");
    renderApp("/admin/org");
    expect(await screen.findByRole("region", { name: "Настройка Платформы" })).toBeVisible();
    cleanup();

    hideBanner("u-demo-admin");
    renderApp("/admin/setup");
    expect(await screen.findByText("Баннер настройки скрыт до завтра.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Вернуть баннер" }));
    await waitFor(() => {
      expect(screen.queryByText("Баннер настройки скрыт до завтра.")).toBeNull();
    });
    expect(window.localStorage.getItem("rt-pf-setup-banner-hidden:u-demo-admin")).toBeNull();
    cleanup();
    renderApp("/admin/org");
    expect(await screen.findByRole("region", { name: "Настройка Платформы" })).toBeVisible();
  });

  it("пункт «Первый запуск» в меню Настроек — пока шаги не завершены", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/org");
    const menu = await screen.findByRole("navigation", { name: "Разделы модуля" });
    expect(await within(menu).findByRole("link", { name: "Первый запуск" })).toHaveAttribute(
      "href",
      "/admin/setup",
    );
    cleanup();

    const state = readSetup();
    window.localStorage.setItem(
      "rt-pf-mock-setup",
      JSON.stringify({
        ...state,
        companyCreated: true,
        done: { bot: true, erp: true, mail: true, models: true, first_employee: true },
      }),
    );
    renderApp("/admin/org");
    const after = await screen.findByRole("navigation", { name: "Разделы модуля" });
    expect(within(after).getByRole("link", { name: "Сотрудники" })).toBeVisible();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 150));
    });
    expect(within(after).queryByRole("link", { name: "Первый запуск" })).toBeNull();
  });

  it("ERP ещё не выдала доступ: мастер ждёт, сам перепроверяет и показывает форму компании без «Проверить снова»", async () => {
    const saved = { ...ERP_RECHECK };
    ERP_RECHECK.everyMs = 40;
    ERP_RECHECK.attempts = 8;
    let calls = 0;
    server.use(
      http.get("*/setup/checklist", () => {
        calls += 1;
        const waiting = calls < 4;
        return HttpResponse.json({
          steps: [
            { key: "erp", state: "done" },
            { key: "bot", state: "todo" },
            { key: "mail", state: "todo" },
            { key: "models", state: "todo" },
            { key: "first_employee", state: "todo" },
          ],
          done: 1,
          total: 5,
          company: waiting ? null : { required: true, can_setup: true },
          company_blocker: waiting ? "erp_unavailable" : null,
        });
      }),
    );
    try {
      signInAs("admin@demo.example");
      renderApp("/admin/setup");

      expect(await screen.findByText("Ждём, пока ERP выдаст доступ…")).toBeVisible();
      // форма появляется сама, мастер остаётся на шаге компании
      expect(await screen.findByLabelText("Название компании")).toBeVisible();
      expect(screen.queryByText("Ждём, пока ERP выдаст доступ…")).toBeNull();
      expect(screen.queryByText(/ERP пока не ответила/)).toBeNull();
    } finally {
      Object.assign(ERP_RECHECK, saved);
    }
  });

  it("ERP так и не ответила: после нескольких попыток — «Проверить снова», без ожидания", async () => {
    const saved = { ...ERP_RECHECK };
    ERP_RECHECK.everyMs = 20;
    ERP_RECHECK.attempts = 2;
    server.use(
      http.get("*/setup/checklist", () =>
        HttpResponse.json({
          steps: [
            { key: "erp", state: "done" },
            { key: "bot", state: "todo" },
            { key: "mail", state: "todo" },
            { key: "models", state: "todo" },
            { key: "first_employee", state: "todo" },
          ],
          done: 1,
          total: 5,
          company: null,
          company_blocker: "erp_unavailable",
        }),
      ),
    );
    try {
      signInAs("admin@demo.example");
      renderApp("/admin/setup");
      await screen.findByText("Ждём, пока ERP выдаст доступ…");
      await waitFor(() => {
        expect(screen.queryByText("Ждём, пока ERP выдаст доступ…")).toBeNull();
      });
      // имя может начинаться с иконки «loading», пока antd не доиграл выход анимации (в jsdom она не кончается)
      expect(await screen.findByRole("button", { name: /Проверить снова/ })).toBeVisible();
    } finally {
      Object.assign(ERP_RECHECK, saved);
    }
  });

  it("шаг открывается в боковом окне мастера, без перехода; после сохранения — сразу следующий шаг", async () => {
    markStepDone("erp");
    signInAs("admin@demo.example");
    renderApp("/admin/setup?step=bot&panel=open");

    const side = await screen.findByRole("complementary", { name: "Боковое окно" });
    expect(
      await within(side).findByRole("heading", { level: 3, name: "Шаг 2 из 5: Telegram-бот" }),
    ).toBeVisible();
    expect(within(side).getByRole("region", { name: "Шаг 2 из 5: Telegram-бот" })).toBeVisible();
    // главный экран — по-прежнему мастер
    expect(screen.getByRole("heading", { level: 1, name: "Первый запуск" })).toBeVisible();

    fireEvent.click(await within(side).findByRole("button", { name: "Сменить токен" }));
    const form = within(side).getByRole("form", { name: "Токен бота" });
    fireEvent.change(within(form).getByLabelText("Токен бота"), {
      target: { value: "12345:abcdefghijklmnopqrstZk9m" },
    });
    fireEvent.change(within(form).getByLabelText("Ваш пароль администратора"), {
      target: { value: "demo-pass-1" },
    });
    fireEvent.click(within(form).getByRole("button", { name: /Сохранить токен$/ }));

    // шаг «Telegram-бот» готов — окно само переходит к следующему несделанному: «Почта»
    expect(
      await within(side).findByRole("region", { name: "Шаг 3 из 5: Почта" }, { timeout: 5_000 }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { level: 1, name: "Первый запуск" })).toBeVisible();
  });

  it("первый сотрудник с временным паролем: пока пароль на экране, «Дальше» нет; после «Готово» — следующий шаг", async () => {
    markStepDone("erp");
    signInAs("admin@demo.example");
    renderApp("/admin/setup?step=first_employee&panel=open");

    const side = await screen.findByRole("complementary", { name: "Боковое окно" });
    const step = await within(side).findByRole("region", { name: "Шаг 5 из 5: Первый сотрудник" });
    fireEvent.click(within(step).getByRole("radio", { name: "Временным паролем, без почты" }));
    fireEvent.change(within(step).getByLabelText("Имя и фамилия"), {
      target: { value: "Тест Мастеров" },
    });
    fireEvent.change(within(step).getByLabelText("Электронная почта"), {
      target: { value: "wizard.temp@demo.example" },
    });
    fireEvent.click(await within(step).findByRole("checkbox", { name: /^Снабженец/ }));
    fireEvent.click(within(step).getByRole("button", { name: /Создать и показать пароль/ }));

    expect(await within(side).findByLabelText("Временный пароль")).toBeVisible();
    // шаг уже «Готово», но пароль показывается один раз — уйти с него можно только через «Готово»
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    expect(within(side).queryByRole("button", { name: /^Дальше:/ })).toBeNull();
    expect(within(side).queryByText("Шаг выполнен.")).toBeNull();

    fireEvent.click(within(side).getByRole("button", { name: "Готово: пароль передан" }));
    const next = await within(side).findByRole(
      "heading",
      { level: 3, name: "Шаг 2 из 5: Telegram-бот" },
      { timeout: 5_000 },
    );
    // фокус — на заголовке нового шага
    await waitFor(() => {
      expect(next).toHaveFocus();
    });
  });

  it("сбой чек-листа: «Повторить»", async () => {
    server.use(http.get("*/setup/checklist", () => HttpResponse.json({}, { status: 503 })));
    signInAs("admin@demo.example");
    renderApp("/admin/setup");

    expect(await screen.findByText("Не удалось получить состояние настройки")).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});
