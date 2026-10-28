import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DEMO_WRONG_PASSWORD } from "../../../mocks/fixtures/users";
import { panelEl, renderAt, signIn, setupIntegrationsTests } from "./testkit";

setupIntegrationsTests();

const PASSWORD = "demo-pass-1";

async function openPanel(card: string, email = "admin@demo.example"): Promise<HTMLElement> {
  signIn(email);
  renderAt(`/admin/integrations?card=${card}&panel=open`);
  return panelEl();
}

/** Подключение бота — вкладка Настроек · Telegram-бот (W15-H4), не боковое окно «Подключений». */
async function openBotConnection(email = "admin@demo.example"): Promise<HTMLElement> {
  signIn(email);
  renderAt("/admin/bot?part=connection");
  return screen.findByRole("tabpanel");
}

function type(label: string | RegExp, value: string, root: HTMLElement = document.body) {
  fireEvent.change(within(root).getByLabelText(label), { target: { value } });
}

/** Кнопка antd в загрузке держит значок «loading» в имени, пока идёт его анимация — имя ищем по хвосту. */
function press(root: HTMLElement, name: string) {
  fireEvent.click(within(root).getByRole("button", { name: new RegExp(`(^|loading)${name}$`) }));
}

function attention(): HTMLElement {
  const section = screen
    .getByRole("heading", { level: 2, name: "Требует внимания" })
    .closest("section");
  if (!section) throw new Error("нет раздела «Требует внимания»");
  return section;
}

function submitPassword(form: HTMLElement, password = PASSWORD) {
  type("Ваш пароль администратора", password, form);
}

describe("Telegram в «Подключениях» — кратко (W15-H4)", () => {
  it("состояние бота и «Настроить бота», без формы токена и канала", async () => {
    const side = await openPanel("telegram");
    expect(await within(side).findByText("@demo_railtech_bot")).toBeVisible();
    expect(within(side).getByRole("link", { name: "Настроить бота" })).toHaveAttribute(
      "href",
      "/admin/bot?part=connection",
    );
    expect(within(side).queryByRole("button", { name: "Сменить токен" })).toBeNull();
    expect(within(side).queryByRole("button", { name: "Тестовое сообщение" })).toBeNull();
  });
});

describe("карточка ERP", () => {
  it("состояние сопряжения с масками; «Проверить связь» отвечает словами", async () => {
    const side = await openPanel("erp");

    expect(await within(side).findByText("Сопряжена")).toBeVisible();
    expect(within(side).getByText("http://erp-backend:8000")).toBeVisible();
    expect(within(side).getByText("•••• 9f3c")).toBeVisible();
    expect(within(side).getByText("•••• 77de")).toBeVisible();

    fireEvent.click(within(side).getByRole("button", { name: "Проверить связь" }));

    expect(await within(side).findByText("ERP отвечает")).toBeVisible();
    expect(within(side).getByText(/версия 1\.9\.0/)).toBeVisible();
  });

  it("подключить ERP: неверный пароль и неверный код — словами у формы; успех — сопряжение и проверка", async () => {
    const side = await openPanel("erp");
    fireEvent.click(await within(side).findByRole("button", { name: "Подключить заново" }));
    const form = within(side).getByRole("form", { name: "Подключить ERP" });
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    expect(within(form).getByRole("button", { name: "Подключить ERP" })).toBeDisabled();

    submitPassword(form, DEMO_WRONG_PASSWORD);
    press(form, "Подключить ERP");
    expect(await within(form).findByRole("alert")).toHaveTextContent("Пароль указан неверно.");
    expect(within(form).getByLabelText("Ваш пароль администратора")).toHaveAttribute(
      "aria-invalid",
      "true",
    );

    type("Одноразовый код сопряжения", "000000", form);
    submitPassword(form);
    press(form, "Подключить ERP");
    await waitFor(() => {
      expect(within(form).getByRole("alert")).toHaveTextContent("Код сопряжения не подошёл.");
    });

    type("Одноразовый код сопряжения", "123456", form);
    press(form, "Подключить ERP");
    expect(await within(side).findByText("Сопряжение выполнено.")).toBeVisible();
    expect(await within(side).findByText("ERP отвечает")).toBeVisible();
    // ключи обновились: в панели только маска, ни кода, ни пароля
    await waitFor(() => {
      expect(within(side).getByText("•••• 5a1d")).toBeVisible();
    });
    expect(document.body.textContent).not.toContain("123456");
    // форма закрыта, код и пароль из неё ушли: при повторном открытии поля пустые
    expect(within(side).queryByRole("form", { name: "Подключить ERP" })).not.toBeInTheDocument();
    // итог остаётся на панели и после закрытия формы
    expect(within(side).getByText("Сопряжение выполнено.")).toBeVisible();
    fireEvent.click(within(side).getByRole("button", { name: "Подключить заново" }));
    const again = within(side).getByRole("form", { name: "Подключить ERP" });
    expect(within(again).getByLabelText("Одноразовый код сопряжения")).toHaveValue("");
    expect(within(again).getByLabelText("Ваш пароль администратора")).toHaveValue("");
  });

  it("ротация ключа: блок «Что произойдёт», пароль, итог; на карточке — переход на новые ключи", async () => {
    const side = await openPanel("erp");
    fireEvent.click(await within(side).findByRole("button", { name: "Ротация ключа" }));
    const form = within(side).getByRole("form", { name: "Ротация ключей ERP" });
    const consequence = within(form).getByRole("group", { name: "Что произойдёт" });
    expect(within(consequence).getByText(/Прежние ключи ещё работают/)).toBeVisible();

    submitPassword(form);
    press(form, "Обновить ключи");

    expect(await within(side).findByText("Ключи обновлены.")).toBeVisible();
    expect(await screen.findByText("Идёт переход на новые ключи")).toBeVisible();
    expect(within(side).getByText("•••• e7b2")).toBeVisible();
    expect(
      within(side).queryByRole("form", { name: "Ротация ключей ERP" }),
    ).not.toBeInTheDocument();
    fireEvent.click(within(side).getByRole("button", { name: "Ротация ключа" }));
    expect(
      within(within(side).getByRole("form", { name: "Ротация ключей ERP" })).getByLabelText(
        "Ваш пароль администратора",
      ),
    ).toHaveValue("");
  });
});

describe("карточка Telegram", () => {
  it("токен: ввод, маска, ошибки; сохранённый токен на экране не остаётся", async () => {
    const side = await openBotConnection();
    expect(await within(side).findByText("@demo_railtech_bot")).toBeVisible();
    expect(within(side).getByText("•••• Qw7x")).toBeVisible();

    fireEvent.click(within(side).getByRole("button", { name: "Сменить токен" }));
    const form = within(side).getByRole("form", { name: "Токен бота" });
    expect(within(form).getByRole("button", { name: "Сохранить токен" })).toBeDisabled();

    const token = `12345:${"abcdefghijklmnopqrstuvwxyz".slice(0, 20)}Zk9m`;
    type("Токен бота", "bad-0000000000000000000000", form);
    submitPassword(form);
    press(form, "Сохранить токен");
    expect(await within(form).findByRole("alert")).toHaveTextContent("Telegram не принял токен");

    type("Токен бота", token, form);
    press(form, "Сохранить токен");
    expect(await screen.findByText("Токен сохранён")).toBeVisible();
    await waitFor(() => {
      expect(within(side).getByText("•••• Zk9m")).toBeVisible();
    });
    expect(within(side).queryByRole("form", { name: "Токен бота" })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(token);
  });

  it("канал команды: список чатов, подключить, тестовое сообщение", async () => {
    const side = await openBotConnection();
    expect(await within(side).findByText("Подключён: Команда RailTech (демо)")).toBeVisible();

    fireEvent.click(
      await within(side).findByRole("button", {
        name: "Подключить канал: Склад и логистика (демо)",
      }),
    );
    expect(await within(side).findByText("Подключён: Склад и логистика (демо)")).toBeVisible();

    fireEvent.click(within(side).getByRole("button", { name: "Тестовое сообщение" }));
    expect(await screen.findByText("Тестовое сообщение отправлено в канал")).toBeVisible();
  });

  it("профиль бота: счётчик, слишком длинный текст блокирует сохранение, сохранение публикует", async () => {
    const side = await openBotConnection();
    const name = await within(side).findByLabelText("Имя бота");
    expect(name).toHaveValue("RailTech Помощник");

    fireEvent.change(name, { target: { value: "Б".repeat(65) } });
    expect(
      await within(side).findByText("Текст длиннее допустимого: сократите отмеченные поля."),
    ).toBeVisible();
    expect(within(side).getByRole("button", { name: "Сохранить и опубликовать" })).toBeDisabled();

    fireEvent.change(name, { target: { value: "RailTech Бот" } });
    fireEvent.click(within(side).getByRole("button", { name: "Сохранить и опубликовать" }));
    expect(await screen.findByText("Профиль бота сохранён")).toBeVisible();
    expect(await within(side).findByText(/Опубликовано в Telegram:/)).toBeVisible();
  });
});

describe("карточка «Почта»", () => {
  it("проверить связь, «Проверить отправку» с итогом словами; журнал доставки CRM и ERP, фильтр по статусу", async () => {
    const side = await openPanel("mail");
    expect(await within(side).findByText("smtp.demo.example:587")).toBeVisible();
    expect(within(side).getByText("•••• k3Zp")).toBeVisible();

    fireEvent.click(within(side).getByRole("button", { name: "Проверить связь" }));
    expect(await within(side).findByText("Сервер принял соединение и вход")).toBeVisible();

    fireEvent.click(within(side).getByRole("button", { name: "Проверить отправку" }));
    expect(
      await within(side).findByText(
        "Письмо отправлено на admin@demo.example: почтовый сервер его принял.",
      ),
    ).toBeVisible();
    await waitFor(() => {
      const log = within(side).getByRole("list", { name: "Журнал доставки" });
      expect(within(log).getByText("Тестовое письмо")).toBeVisible();
    });

    // W18A-P1: письма ERP — в том же журнале, с источником и назначением словами
    const log = within(side).getByRole("list", { name: "Журнал доставки" });
    expect(within(log).getByText("ERP · КП клиенту · вложение: 1")).toBeVisible();
    expect(
      within(log).getByText("Причина: Почтовый сервер отклонил письмо (SMTP 550)"),
    ).toBeVisible();

    // фильтр: только ошибки
    fireEvent.mouseDown(within(side).getByLabelText("Показать"));
    fireEvent.click(await screen.findByTitle("Ошибка"));
    await waitFor(() => {
      const filtered = within(side).getByRole("list", { name: "Журнал доставки" });
      expect(within(filtered).queryByText("Тестовое письмо")).not.toBeInTheDocument();
      expect(within(filtered).getByText("Оповещение о сбое сервиса")).toBeVisible();
    });
    expect(within(side).getByText("Причина: smtp_unavailable")).toBeVisible();
  });

  it("настройки SMTP: пароль SMTP и пароль администратора, ошибка поля, сохранение", async () => {
    const side = await openPanel("mail");
    fireEvent.click(await within(side).findByRole("button", { name: "Настроить SMTP" }));
    const form = within(side).getByRole("form", { name: "Настройки SMTP" });

    type("Сервер (хост)", "bad host", form);
    submitPassword(form);
    press(form, "Сохранить настройки");
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Сервер почты указан неверно.",
    );

    type("Сервер (хост)", "smtp2.demo.example", form);
    type("Пароль SMTP", "new-smtp-secret-9z1q", form);
    press(form, "Сохранить настройки");
    expect(await screen.findByText("Настройки почты сохранены")).toBeVisible();
    await waitFor(() => {
      expect(within(side).getByText("smtp2.demo.example:587")).toBeVisible();
      expect(within(side).getByText("•••• 9z1q")).toBeVisible();
    });
    expect(document.body.textContent).not.toContain("new-smtp-secret-9z1q");
  });
});

describe("карточка «Внешние сервисы»", () => {
  it("«Проверить» обновляет сервис; выключатель — «Что произойдёт», пароль, затем включить", async () => {
    const side = await openPanel("services");
    expect(await within(side).findByText("Telegram Bot API")).toBeVisible();

    fireEvent.click(within(side).getByRole("button", { name: "Проверить сервис: Почта (SMTP)" }));
    await waitFor(() => {
      expect(within(side).queryByText(/В очереди 3 письма/)).not.toBeInTheDocument();
    });

    fireEvent.click(
      within(side).getByRole("button", { name: "Выключить сервис: Telegram Bot API" }),
    );
    const form = within(side).getByRole("form", { name: "Выключить сервис: Telegram Bot API" });
    expect(
      within(within(form).getByRole("group", { name: "Что произойдёт" })).getByText(
        "Бот перестанет отвечать клиентам; сообщения встанут в очередь",
      ),
    ).toBeVisible();
    type("Причина (попадёт в журнал)", "профилактика", form);
    submitPassword(form, DEMO_WRONG_PASSWORD);
    press(form, "Выключить сервис");
    expect(await within(form).findByRole("alert")).toHaveTextContent("Пароль указан неверно.");

    submitPassword(form);
    press(form, "Выключить сервис");
    expect(await within(side).findByText("выключено вручную")).toBeVisible();
    expect(within(side).getByText("Причина: профилактика")).toBeVisible();
    // на карточке Telegram — пометка, в «Требует внимания» — строка
    await waitFor(() => {
      expect(within(attention()).getByText(/Сервис выключен вручную/)).toBeVisible();
    });

    fireEvent.click(
      within(side).getByRole("button", { name: "Включить сервис: Telegram Bot API" }),
    );
    const enable = within(side).getByRole("form", { name: "Включить сервис: Telegram Bot API" });
    submitPassword(enable);
    press(enable, "Включить сервис");
    await waitFor(() => {
      expect(within(side).queryByText("выключено вручную")).not.toBeInTheDocument();
    });
  });

  it("у сервиса без выключателя кнопки «Выключить» нет", async () => {
    const side = await openPanel("services");
    await within(side).findByText("Хранилище файлов (S3)");
    expect(
      within(side).queryByRole("button", { name: "Выключить сервис: Хранилище файлов (S3)" }),
    ).not.toBeInTheDocument();
    expect(
      within(side).getByRole("button", { name: "Проверить сервис: Хранилище файлов (S3)" }),
    ).toBeVisible();
  });
});

describe("карточка «Модели ИИ»", () => {
  it("проверка модели, смена с ключом (ключ не показывается), сброс", async () => {
    const side = await openPanel("models");
    expect(await within(side).findByText("Поиск по базе знаний")).toBeVisible();
    // сырой текст провайдера в строках ролей — только под «Техническими подробностями» (свёрнуто)
    expect(within(side).queryAllByText("401: ключ отклонён провайдером")).toHaveLength(0);
    const embedRow = within(side).getByText("Поиск по базе знаний").closest("li");
    fireEvent.click(
      within(embedRow as HTMLElement).getByRole("button", { name: "Технические подробности" }),
    );
    expect(
      within(embedRow as HTMLElement).getByText("401: ключ отклонён провайдером"),
    ).toBeVisible();
    // маска ключа: источник и последние 4 символа, сам ключ не приходит
    const dialog = within(side).getByText("Диалог с клиентом").closest("li");
    expect(within(dialog as HTMLElement).getByText("•••• 77aa")).toBeVisible();
    expect(within(dialog as HTMLElement).getByText(/задан в Платформе/)).toBeVisible();
    const qualifier = within(side).getByText("Квалификатор лида").closest("li");
    expect(within(qualifier as HTMLElement).getByText(/из настроек сервера/)).toBeVisible();

    fireEvent.click(
      within(side).getByRole("button", { name: "Проверить модель: Поиск по базе знаний" }),
    );
    const confirm = within(side).getByRole("form", {
      name: "Проверка модели «Поиск по базе знаний»",
    });
    expect(
      within(within(confirm).getByRole("group", { name: "Что произойдёт" })).getByText(
        /один короткий платный запрос/,
      ),
    ).toBeVisible();
    // запроса к модели без подтверждения нет
    expect(within(side).queryByText(/не ответила/)).not.toBeInTheDocument();
    press(confirm, "Проверить модель");
    expect(
      await within(side).findByText("Модель «Поиск по базе знаний» не ответила"),
    ).toBeVisible();

    fireEvent.click(
      within(side).getByRole("button", { name: "Сменить модель: Поиск по базе знаний" }),
    );
    const form = within(side).getByRole("form", { name: "Сменить модель: Поиск по базе знаний" });
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    type("Модель", "embedding-demo-2", form);
    type("Ключ провайдера", "demo-provider-key-91zx", form);
    submitPassword(form);
    press(form, "Сменить модель");

    expect(
      await within(side).findByText("Модель сменена: openai · embedding-demo-2"),
    ).toBeVisible();
    expect(
      within(side).getByText("Ключ задан в Платформе и хранится зашифрованным."),
    ).toBeVisible();
    expect(
      within(side).getByText("Для поиска по базе знаний нужна переиндексация документов."),
    ).toBeVisible();
    expect(document.body.textContent).not.toContain("demo-provider-key-91zx");
    const embed = within(side).getByText("Поиск по базе знаний").closest("li");
    await waitFor(() => {
      expect(within(embed as HTMLElement).getByText("•••• 91zx")).toBeVisible();
    });
    // у поставщика остаётся роль с проблемой («Проверка качества») — строка группы пока на месте
    expect(within(attention()).getByText(/Ключ OpenAI отклонён/)).toBeVisible();

    fireEvent.click(
      within(side).getByRole("button", { name: "Сбросить модель: Диалог с клиентом" }),
    );
    const reset = within(side).getByRole("form", { name: "Сбросить модель: Диалог с клиентом" });
    expect(within(reset).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    submitPassword(reset);
    press(reset, "Сбросить к значению по умолчанию");
    expect(await within(side).findByText("Используется ключ из настроек сервера.")).toBeVisible();
    await waitFor(() => {
      const row = within(side).getByText("Диалог с клиентом").closest("li");
      expect(within(row as HTMLElement).queryByText("•••• 77aa")).not.toBeInTheDocument();
      expect(
        within(row as HTMLElement).getByText("Ключ: из настроек сервера", { selector: "p" }),
      ).toBeVisible();
    });
  });

  it("«Сменить»: поле «Модель» без префикса провайдера, подсказка с примером", async () => {
    const side = await openPanel("models");
    const row = (await within(side).findByText("Диалог с клиентом")).closest("li");
    // в строке роли — имя без префикса, хотя CRM отдаёт «anthropic/claude-demo-chat»
    expect(within(row as HTMLElement).getByText(/anthropic · claude-demo-chat/)).toBeVisible();
    expect(within(row as HTMLElement).queryByText(/anthropic\/claude-demo-chat/)).toBeNull();

    fireEvent.click(
      within(side).getByRole("button", { name: "Сменить модель: Диалог с клиентом" }),
    );
    const form = within(side).getByRole("form", { name: "Сменить модель: Диалог с клиентом" });
    expect(within(form).getByLabelText("Модель")).toHaveValue("claude-demo-chat");
    expect(within(form).getByLabelText("Модель")).not.toHaveAttribute("aria-invalid");
    expect(within(form).getByText(/Префикс «anthropic\/» вводить не нужно/)).toBeVisible();
  });

  it("«Сменить»: префикс выбранного провайдера принимается", async () => {
    const side = await openPanel("models");
    fireEvent.click(
      await within(side).findByRole("button", { name: "Сменить модель: Диалог с клиентом" }),
    );
    const form = within(side).getByRole("form", { name: "Сменить модель: Диалог с клиентом" });
    type("Модель", "anthropic/claude-demo-chat-2", form);
    type("Ключ провайдера", "demo-provider-key-91zx", form);
    submitPassword(form);
    press(form, "Сменить модель");

    expect(
      await within(side).findByText("Модель сменена: anthropic · claude-demo-chat-2"),
    ).toBeVisible();
  });

  it("«Сменить»: чужой префикс — 422 по полю: подсвечено, понятный текст, ключ и пароль на месте", async () => {
    const side = await openPanel("models");
    fireEvent.click(
      await within(side).findByRole("button", { name: "Сменить модель: Диалог с клиентом" }),
    );
    const form = within(side).getByRole("form", { name: "Сменить модель: Диалог с клиентом" });
    type("Модель", "openai/gpt-demo", form);
    type("Ключ провайдера", "demo-provider-key-91zx", form);
    submitPassword(form);
    press(form, "Сменить модель");

    const alert = await within(form).findByRole("alert");
    expect(alert).toHaveTextContent(/Имя модели не принято/);
    expect(alert).not.toHaveTextContent("Проверьте заполнение полей");
    const field = within(form).getByLabelText("Модель");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field.getAttribute("aria-describedby")).toContain("model-dialog-model-error");
    expect(field.closest(".ant-input")).toHaveClass("ant-input-status-error");
    expect(within(form).getByLabelText("Ключ провайдера")).not.toHaveAttribute("aria-invalid");
    // секретные поля не очищаются: исправить имя и отправить снова можно без повторного ввода
    expect(within(form).getByLabelText("Ключ провайдера")).toHaveValue("demo-provider-key-91zx");
    expect(within(form).getByLabelText("Ваш пароль администратора")).toHaveValue(PASSWORD);

    type("Модель", "claude-demo-chat-2", form);
    press(form, "Сменить модель");
    expect(
      await within(side).findByText("Модель сменена: anthropic · claude-demo-chat-2"),
    ).toBeVisible();
  });

  it("директор читает модели и маску ключа, кнопок изменения нет", async () => {
    const side = await openPanel("models", "director@demo.example");
    expect(await within(side).findByText("Диалог с клиентом")).toBeVisible();
    expect(within(side).getAllByText("•••• 77aa").length).toBeGreaterThan(0);
    expect(
      within(side).queryByRole("button", { name: /^(Проверить|Сменить|Сбросить) модель/ }),
    ).not.toBeInTheDocument();
    expect(
      within(side).getByText("Режим просмотра: изменения доступны администратору."),
    ).toBeVisible();
  });
});

describe("карточка «Хранилище и бэкапы»", () => {
  it("копии и «Сделать копию сейчас» с блоком «Что произойдёт»", async () => {
    const side = await openPanel("storage");
    expect(await within(side).findByText("crm-2026-10-26.dump")).toBeVisible();
    expect(within(side).getByText("свежая")).toBeVisible();

    fireEvent.click(within(side).getByRole("button", { name: "Сделать копию сейчас" }));
    const form = within(side).getByRole("form", { name: "Копия вне расписания" });
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    press(form, "Запросить копию");

    expect(await screen.findByText("Запрос на копию отправлен")).toBeVisible();
    expect(await within(side).findByText(/Копия по запросу ожидает сервис бэкапа/)).toBeVisible();
    expect(within(side).getByRole("button", { name: "Сделать копию сейчас" })).toBeDisabled();
  });

  it("директор читает файлы и копии, «Сделать копию» нет", async () => {
    const side = await openPanel("storage", "director@demo.example");
    expect(await within(side).findByText("Хранилище файлов (S3)")).toBeVisible();
    expect(await within(side).findByText("crm-2026-10-26.dump")).toBeVisible();
    expect(
      within(side).queryByRole("button", { name: "Сделать копию сейчас" }),
    ).not.toBeInTheDocument();
  });
});

describe("карточка «Состояние системы»", () => {
  it("компоненты в порядке «сбой, предупреждение, норма», у каждого слово статуса", async () => {
    const side = await openPanel("system");
    const list = await within(side).findByRole("list", { name: "Состояние системы" });
    const titles = within(list)
      .getAllByRole("listitem")
      .map((row) => within(row).getByText(/.+/, { selector: ".pf-int-item-title" }).textContent);
    expect(titles[0]).toBe("Очередь задач");
    expect(within(list).getAllByText("Работает")).toHaveLength(5);
    expect(within(list).getByText("Внимание")).toBeVisible();
  });
});
