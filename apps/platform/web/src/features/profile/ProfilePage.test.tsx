import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { endSession } from "../../mocks/mockSession";
import { TELEGRAM_CONFIRM_KEY, patchProfile, todayIso } from "../../mocks/profileStore";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";

// В jsdom нет canvas: готовый круг заменяем маленьким PNG.
vi.mock("./cropExport", () => ({
  renderCircle: () =>
    Promise.resolve(
      new Blob([Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])], {
        type: "image/png",
      }),
    ),
}));

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

async function openProfile(email = "manager@demo.example") {
  signInAs(email);
  renderApp("/me");
  await screen.findByRole("heading", { level: 1, name: "Профиль" });
  return screen.getByRole("main");
}

/** Пункт открытого выпадающего списка antd по подписи (в списке он продублирован для скринридера). */
async function option(label: string): Promise<Element> {
  return waitFor(() => {
    const found = document.querySelector(`.ant-select-item-option[title^="${label}"]`);
    expect(found).not.toBeNull();
    return found as Element;
  });
}

function block(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

describe("Профиль /me", () => {
  it("страница, а не окно: данные, роли словами, нет «Доступ: CRM · ERP»", async () => {
    const page = await openProfile();
    const data = await within(page).findByRole("region", { name: "Личные данные" });

    expect(within(data).getByText("manager@demo.example")).toBeInTheDocument();
    expect(within(data).getByText("Менеджер по продажам")).toBeInTheDocument();
    expect(within(data).getByText("Менеджер")).toBeInTheDocument(); // роль словами
    expect(page).not.toHaveTextContent("Доступ");
    expect(page).not.toHaveTextContent("CRM · ERP");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.title).toContain("Профиль");
    expect(within(data).queryByRole("textbox", { name: "Должность" })).toBeNull(); // только чтение
  });

  it("«Сохранить» активна только при изменениях, «Отмена» возвращает значения", async () => {
    const page = await openProfile();
    const data = await within(page).findByRole("region", { name: "Личные данные" });
    const save = within(data).getByRole("button", { name: /Сохранить$/ });
    const cancel = within(data).getByRole("button", { name: "Отмена" });
    expect(save).toBeDisabled();
    expect(cancel).toBeDisabled();

    const phone = within(data).getByRole("textbox", { name: "Телефон" });
    fireEvent.change(phone, { target: { value: "+998 90 123-45-67" } });
    await waitFor(() => {
      expect(save).toBeEnabled();
    });

    fireEvent.click(cancel);
    await waitFor(() => {
      expect(phone).toHaveValue("");
    });
    expect(save).toBeDisabled();
  });

  it("сохранение уходит в BFF только с изменёнными полями", async () => {
    const sent: unknown[] = [];
    server.use(
      http.patch("*/me/profile", async ({ request, params: _p }) => {
        sent.push(await request.json());
        return HttpResponse.json({
          name: "Демо Менеджеров",
          email: "manager@demo.example",
          language: "ru",
          timezone: "Asia/Samarkand",
          phone: "+998901234567",
          telegram: { linked: true },
          covering: [],
        });
      }),
    );
    const page = await openProfile();
    const data = await within(page).findByRole("region", { name: "Личные данные" });
    fireEvent.change(within(data).getByRole("textbox", { name: "Телефон" }), {
      target: { value: "+998 90 123-45-67" },
    });
    fireEvent.click(within(data).getByRole("button", { name: /Сохранить$/ }));

    expect(await screen.findByText("Профиль сохранён")).toBeInTheDocument();
    expect(sent).toEqual([{ phone: "+998 90 123-45-67" }]);
    await waitFor(() => {
      expect(within(data).getByRole("button", { name: /Сохранить$/ })).toBeDisabled();
    });
  });

  it("ошибка значения от CRM показана словами по подкоду", async () => {
    const page = await openProfile();
    const data = await within(page).findByRole("region", { name: "Личные данные" });
    // Серверная проверка сильнее клиентской маски: мок отклоняет пояс, которого нет.
    fireEvent.click(within(data).getByRole("combobox", { name: "Часовой пояс" }));
    server.use(
      http.patch("*/me/profile", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "x",
            source: "crm",
            details: { fields: ["timezone"], reason: "timezone_unknown" },
          },
          { status: 422 },
        ),
      ),
    );
    fireEvent.change(within(data).getByRole("textbox", { name: "Телефон" }), {
      target: { value: "+998901234567" },
    });
    fireEvent.click(within(data).getByRole("button", { name: /Сохранить$/ }));

    expect(await within(data).findByRole("alert")).toHaveTextContent("Такого часового пояса нет");
  });

  it("телефон с буквами не уходит на сервер", async () => {
    const page = await openProfile();
    const data = await within(page).findByRole("region", { name: "Личные данные" });
    fireEvent.change(within(data).getByRole("textbox", { name: "Телефон" }), {
      target: { value: "abc" },
    });
    fireEvent.click(within(data).getByRole("button", { name: /Сохранить$/ }));
    expect(await within(data).findByText(/Проверьте номер/)).toBeInTheDocument();
  });
});

describe("Профиль /me → Telegram", () => {
  it("привязка по ссылке: QR и кнопка, подтверждение ботом закрывает окно, статус «Привязан как @…»", async () => {
    const page = await openProfile("engineer@demo.example");
    const telegram = await within(page).findByRole("region", {
      name: "Telegram для уведомлений",
    });
    expect(within(telegram).getByText("Не привязан")).toBeInTheDocument();

    fireEvent.click(within(telegram).getByRole("button", { name: /Привязать Telegram$/ }));
    const dialog = await screen.findByRole("dialog", { name: "Привязка Telegram" });
    expect(
      within(dialog).getByRole("img", { name: "QR-код для привязки Telegram" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Открыть в Telegram" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^https:\/\/t\.me\/rt_demo_bot\?start=staff_/),
    );
    expect(within(dialog).getByText(/Ждём подтверждения/)).toBeInTheDocument();

    // «Нажал Start в боте»: ближайший опрос профиля видит привязку.
    window.localStorage.setItem(`${TELEGRAM_CONFIRM_KEY}-u-demo-engineer`, "engineer_demo");
    expect(await screen.findByText("Telegram привязан", {}, { timeout: 8000 })).toBeInTheDocument();
    expect(await within(telegram).findByText("Привязан как @engineer_demo")).toBeInTheDocument();
    // Подписки стали доступны.
    const notifications = block("Уведомления");
    await waitFor(() => {
      expect(
        within(notifications).getByRole("switch", { name: "Лиды, которые ждут меня" }),
      ).toBeEnabled();
    });
  }, 15_000);

  it("«Отвязать» спрашивает подтверждение и снимает привязку", async () => {
    const page = await openProfile("manager@demo.example");
    const telegram = await within(page).findByRole("region", { name: "Telegram для уведомлений" });
    expect(await within(telegram).findByText("Привязан")).toBeInTheDocument();

    fireEvent.click(within(telegram).getByRole("button", { name: /Отвязать$/ }));
    const confirm = await screen.findByRole("dialog", { name: "Отвязать Telegram?" });
    fireEvent.click(within(confirm).getByRole("button", { name: /Отвязать$/ }));

    expect(await within(telegram).findByText("Не привязан")).toBeInTheDocument();
    expect(
      within(telegram).getByRole("button", { name: /Привязать Telegram$/ }),
    ).toBeInTheDocument();
  });

  it("бот не подключён: понятный отказ вместо пустого окна", async () => {
    server.use(
      http.post("*/me/telegram-link", () =>
        HttpResponse.json({ code: "NOT_CONFIGURED", message: "x", source: "crm" }, { status: 409 }),
      ),
    );
    const page = await openProfile("engineer@demo.example");
    const telegram = await within(page).findByRole("region", { name: "Telegram для уведомлений" });
    fireEvent.click(await within(telegram).findByRole("button", { name: /Привязать Telegram$/ }));

    expect(await within(telegram).findByRole("alert")).toHaveTextContent("Бот не подключён");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Профиль /me → Замещение", () => {
  function pickDate(label: string, value: string) {
    const input = screen.getByLabelText(label);
    fireEvent.mouseDown(input);
    fireEvent.change(input, { target: { value } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 13, charCode: 13 });
    fireEvent.blur(input);
  }

  it("назначение: коллега и даты → фраза «На время отсутствия мои задачи видит …»; снятие", async () => {
    const page = await openProfile("manager@demo.example");
    const deputy = await within(page).findByRole("region", { name: "Замещение" });
    expect(within(deputy).getByText("Замещение не назначено.")).toBeInTheDocument();

    // Неполная форма не уходит.
    fireEvent.click(within(deputy).getByRole("button", { name: /Назначить$/ }));
    expect(await within(deputy).findByRole("alert")).toHaveTextContent(
      "Выберите коллегу и обе даты",
    );

    const select = within(deputy).getByRole("combobox", { name: "Кто замещает" });
    fireEvent.mouseDown(select);
    fireEvent.click(await option("Демо Директоров"));
    const year = new Date().getFullYear() + 1;
    pickDate("С даты", `01.12.${String(year)}`);
    pickDate("По дату", `10.12.${String(year)}`);
    fireEvent.click(within(deputy).getByRole("button", { name: /Назначить$/ }));

    await waitFor(() => {
      expect(within(deputy).getByTestId("deputy-sentence")).toHaveTextContent(
        `На время отсутствия мои задачи видит Демо Директоров с 01.12.${String(year)} по 10.12.${String(year)}.`,
      );
    });

    fireEvent.click(within(deputy).getByRole("button", { name: /Снять замещение$/ }));
    expect(await within(deputy).findByText("Замещение не назначено.")).toBeInTheDocument();
  }, 15_000);

  it("заместитель видит, за кого замещает, и строки замещаемого в «Моей очереди» с пометкой", async () => {
    patchProfile("u-demo-director", {
      deputy: { id: "u-demo-manager", date_from: todayIso(), date_to: todayIso() },
    });
    const page = await openProfile("manager@demo.example");
    const deputy = await within(page).findByRole("region", { name: "Замещение" });
    expect(await within(deputy).findByTestId("covering-list")).toHaveTextContent(
      "Вы замещаете: Демо Директоров",
    );
  });

  it("отказ CRM по подкоду — словами", async () => {
    server.use(
      http.put("*/me/deputy", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "x",
            source: "crm",
            details: { fields: ["deputy_id"], reason: "deputy_period_past" },
          },
          { status: 422 },
        ),
      ),
    );
    const page = await openProfile("manager@demo.example");
    const deputy = await within(page).findByRole("region", { name: "Замещение" });
    const select = within(deputy).getByRole("combobox", { name: "Кто замещает" });
    fireEvent.mouseDown(select);
    fireEvent.click(await option("Демо Директоров"));
    const year = new Date().getFullYear() + 1;
    pickDate("С даты", `01.12.${String(year)}`);
    pickDate("По дату", `10.12.${String(year)}`);
    fireEvent.click(within(deputy).getByRole("button", { name: /Назначить$/ }));

    expect(await within(deputy).findByRole("alert")).toHaveTextContent("Период уже закончился");
  }, 15_000);
});

describe("Профиль /me → Фото", () => {
  it("загрузка: выбор файла → обрезка → сохранение; фото в рейле вместо инициалов; удаление", async () => {
    const page = await openProfile("manager@demo.example");
    const data = await within(page).findByRole("region", { name: "Личные данные" });
    const rail = screen.getByRole("button", { name: /профиль и настройки/i });
    expect(rail.querySelector("img")).toBeNull();
    expect(rail).toHaveTextContent("ДМ");

    const input = within(data).getByLabelText("Загрузить фото", { selector: "input" });
    const file = new File([Uint8Array.from([1, 2, 3, 4])], "me.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });

    const dialog = await screen.findByRole("dialog", { name: "Фото профиля" });
    // jsdom не загружает картинки: сообщаем размеры, как это сделал бы браузер.
    const img = await waitFor(() => {
      const found = dialog.querySelector("img");
      expect(found).not.toBeNull();
      return found as HTMLImageElement;
    });
    Object.defineProperty(img, "naturalWidth", { value: 400 });
    Object.defineProperty(img, "naturalHeight", { value: 300 });
    fireEvent.load(img);
    const apply = within(dialog).getByRole("button", { name: /Сохранить фото$/ });
    await waitFor(() => {
      expect(apply).toBeEnabled();
    });
    expect(within(dialog).getByRole("slider", { name: "Масштаб" })).toBeInTheDocument();
    fireEvent.click(apply);

    expect(await screen.findByText("Фото обновлено")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /профиль и настройки/i }).querySelector("img"),
      ).not.toBeNull();
    });
    expect(
      screen.getByRole("button", { name: /профиль и настройки/i }).querySelector("img"),
    ).toHaveAttribute(
      "src",
      expect.stringMatching(/^\/api\/v1\/staff\/u-demo-manager\/avatar\?v=\d+$/),
    );

    fireEvent.click(within(data).getByRole("button", { name: /Удалить фото$/ }));
    expect(await screen.findByText("Фото удалено")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /профиль и настройки/i }).querySelector("img"),
      ).toBeNull();
    });
  }, 15_000);

  it("файл не картинки отклоняется до обрезки", async () => {
    const page = await openProfile("manager@demo.example");
    const data = await within(page).findByRole("region", { name: "Личные данные" });
    const input = within(data).getByLabelText("Загрузить фото", { selector: "input" });
    fireEvent.change(input, {
      target: { files: [new File(["<svg/>"], "x.svg", { type: "image/svg+xml" })] },
    });

    expect(await within(data).findByRole("alert")).toHaveTextContent(
      "Нужна картинка PNG, JPEG или WebP",
    );
    expect(screen.queryByRole("dialog", { name: "Фото профиля" })).toBeNull();
  });

  it("сервер отклонил фото (слишком большое) — ошибка в окне обрезки, окно остаётся", async () => {
    server.use(
      http.put("*/me/avatar", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "x",
            source: "crm",
            details: { fields: ["avatar"], reason: "avatar_too_large" },
          },
          { status: 422 },
        ),
      ),
    );
    const page = await openProfile("manager@demo.example");
    const data = await within(page).findByRole("region", { name: "Личные данные" });
    const input = within(data).getByLabelText("Загрузить фото", { selector: "input" });
    fireEvent.change(input, {
      target: { files: [new File([Uint8Array.from([1])], "me.png", { type: "image/png" })] },
    });
    const dialog = await screen.findByRole("dialog", { name: "Фото профиля" });
    const img = await waitFor(() => {
      const found = dialog.querySelector("img");
      expect(found).not.toBeNull();
      return found as HTMLImageElement;
    });
    Object.defineProperty(img, "naturalWidth", { value: 100 });
    Object.defineProperty(img, "naturalHeight", { value: 100 });
    fireEvent.load(img);
    const apply = within(dialog).getByRole("button", { name: /Сохранить фото$/ });
    await waitFor(() => {
      expect(apply).toBeEnabled();
    });
    fireEvent.click(apply);

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Фото больше 1 МБ");
  }, 15_000);
});

describe("«Моя очередь» заместителя", () => {
  it("строки замещаемого — с пометкой «за {имя}», свои — без неё", async () => {
    patchProfile("u-demo-director", {
      deputy: { id: "u-demo-manager", date_from: todayIso(), date_to: todayIso() },
    });
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");

    const queue = await screen.findByRole("region", { name: "Что сделать сейчас" });
    const covered = await within(queue).findByText(/^за Демо Директоров · /);
    expect(covered).toBeInTheDocument();
    const rows = within(queue).getAllByRole("listitem");
    expect(rows.filter((row) => /за Демо Директоров/.test(row.textContent ?? ""))).toHaveLength(1);
    expect(rows.length).toBeGreaterThan(1);
  });
});
