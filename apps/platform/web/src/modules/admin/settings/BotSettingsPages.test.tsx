import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";

setupBotTests();

/**
 * Разделы бывшего «Telegram-бота» после SET-IA — на страницах своих групп Настроек: Каналы связи · Telegram (вкладки
 * «Подключение · Тексты · Поведение · Шаблоны ответов · База знаний»), Время и сроки, Уведомления, Формы сайта, Справочники
 * (причины отказа), Реквизиты и бланк (контакты для клиентов), Расходы на ИИ (дневной лимит), Выгрузки.
 */
async function openPage(email: string, path: string, title: string) {
  signIn(email);
  const view = renderAt(path);
  expect(await screen.findByRole("heading", { level: 1, name: title })).toBeVisible();
  return view;
}

const openTelegram = (email: string, search = "") =>
  openPage(email, `/admin/telegram${search}`, "Telegram");

function tab(name: string) {
  fireEvent.click(
    within(screen.getByRole("tablist", { name: "Разделы Telegram-бота" })).getByRole("tab", {
      name,
    }),
  );
}

/** Форма раздела бота на странице — область с заголовком раздела. */
async function form(name: string) {
  return screen.findByRole("region", { name });
}

describe("Настройки · Telegram и разделы бота по группам (SET-IA)", () => {
  it("Telegram: один уровень вкладок «Подключение · Тексты · Поведение · Шаблоны ответов · База знаний»", async () => {
    await openTelegram("admin@demo.example");
    const tabs = screen.getByRole("tablist", { name: "Разделы Telegram-бота" });
    expect(
      within(tabs)
        .getAllByRole("tab")
        .map((t) => t.textContent),
    ).toEqual(["Подключение", "Тексты", "Поведение", "Шаблоны ответов", "База знаний"]);
    expect(within(tabs).getByRole("tab", { name: "Подключение" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(await screen.findByText("@demo_railtech_bot")).toBeVisible();
    expect(screen.getByRole("button", { name: "Сменить токен" })).toBeVisible();
    // без вложенной навигации разделов внутри вкладки
    expect(screen.queryByRole("navigation", { name: "Разделы настроек бота" })).toBeNull();

    tab("База знаний");
    expect(await screen.findByRole("link", { name: "Открыть базу знаний" })).toHaveAttribute(
      "href",
      "/crm/kb",
    );
    expect(await screen.findByText("Минимальное сходство, чтобы бот отвечал (0–1)")).toBeVisible();
  });

  it("«Поведение»: поведение бота, квалификация, стоп-слова и конкуренты — формами одна под другой", async () => {
    await openTelegram("admin@demo.example", "?tab=behavior");
    const expectations: Record<string, string> = {
      "Поведение бота": "Максимум слов в ответе",
      Квалификация: "Обязательные факты",
      "Стоп-слова": "Слова",
      Конкуренты: "Слова",
    };
    for (const [name, label] of Object.entries(expectations)) {
      expect(await within(await form(name)).findAllByText(label)).not.toHaveLength(0);
    }
    // Разделы других групп сюда не попали
    expect(screen.queryByRole("region", { name: "Правила передачи" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Причины отказа" })).toBeNull();
  });

  it("каждый раздел бота — на странице своей группы и подписан на языке сотрудника", async () => {
    const pages: [string, string, string, string][] = [
      ["/admin/timing", "Время и сроки", "Рабочие часы", "Начало рабочего дня"],
      ["/admin/timing", "Время и сроки", "Правила передачи", "Оценка лида для передачи"],
      ["/admin/notifications", "Уведомления", "Канал команды", "Дежурные"],
      [
        "/admin/notifications",
        "Уведомления",
        "Оповещения о сбоях сервисов",
        "Личное сообщение админам в Telegram",
      ],
      [
        "/admin/web-forms",
        "Формы сайта",
        "Форма «Заявка» с сайта",
        "Минимальное время заполнения формы",
      ],
      ["/admin/dictionaries?list=deals", "Справочники", "Причины отказа", "Причины отказа"],
      ["/admin/ai-spend", "Расходы на ИИ", "Бюджет моделей", "Дневной бюджет"],
      ["/admin/company", "Реквизиты и бланк", "Контакты для клиентов", "Название компании"],
    ];
    for (const [path, title, section, label] of pages) {
      const { router } = await openPage("admin@demo.example", path, title);
      expect(await within(await form(section)).findAllByText(label)).not.toHaveLength(0);
      router.dispose();
    }
  });

  it("канал команды выбирается в «Telegram · Подключение» — ссылка туда из «Уведомлений»", async () => {
    await openPage("admin@demo.example", "/admin/notifications", "Уведомления");
    const channel = await form("Канал команды");
    expect(within(channel).queryByLabelText("ID приватного канала")).toBeNull();
    expect(within(channel).getByRole("link", { name: "Открыть «Telegram»" })).toHaveAttribute(
      "href",
      "/admin/telegram",
    );
  });

  it("сохранение раздела: «Есть несохранённые изменения», сообщение; «Отменить изменения» возвращает значения", async () => {
    await openPage("admin@demo.example", "/admin/company", "Реквизиты и бланк");
    const contacts = await form("Контакты для клиентов");
    const name = await within(contacts).findByLabelText("Название компании");

    fireEvent.change(name, { target: { value: "RailTech Групп (демо)" } });
    expect(await within(contacts).findByText("Есть несохранённые изменения")).toBeVisible();
    fireEvent.click(within(contacts).getByRole("button", { name: "Отменить изменения" }));
    await waitFor(() => {
      expect(within(contacts).getByLabelText("Название компании")).toHaveValue("RailTech (демо)");
    });

    fireEvent.change(within(contacts).getByLabelText("Название компании"), {
      target: { value: "RailTech Групп (демо)" },
    });
    fireEvent.click(within(contacts).getByRole("button", { name: /Сохранить/ }));
    expect(await screen.findByText("Настройки «Контакты для клиентов» сохранены")).toBeVisible();
    await waitFor(() => {
      expect(within(contacts).getByText("Изменений нет")).toBeVisible();
    });
    // Сохранение настройки — без «Что произойдёт» (CONVENTIONS §2 п. 8, S1)
    expect(within(contacts).queryByRole("group", { name: "Что произойдёт" })).toBeNull();
  });

  it("CRM не принимает значение: путь поля из ответа подсвечивает поле, сохранить после исправления можно", async () => {
    await openPage("admin@demo.example", "/admin/company", "Реквизиты и бланк");
    const contacts = await form("Контакты для клиентов");
    fireEvent.change(await within(contacts).findByLabelText("Название компании"), {
      target: { value: "   " },
    });
    fireEvent.click(within(contacts).getByRole("button", { name: /Сохранить/ }));
    expect(
      await within(contacts).findByText("Значения не приняты: проверьте отмеченные поля."),
    ).toBeVisible();
    fireEvent.change(within(contacts).getByLabelText("Название компании"), {
      target: { value: "Рельсы Демо" },
    });
    fireEvent.click(await within(contacts).findByRole("button", { name: /Сохранить/ }));
    expect(await screen.findByText("Настройки «Контакты для клиентов» сохранены")).toBeVisible();
  });

  it("рабочие часы: время, дни недели, праздники и часовой пояс — типизированные поля", async () => {
    await openPage("admin@demo.example", "/admin/timing", "Время и сроки");
    const hours = await form("Рабочие часы");
    expect(await within(hours).findByLabelText("Начало рабочего дня")).toHaveValue("09:00");
    expect(within(hours).getByLabelText("Конец рабочего дня")).toHaveValue("18:00");
    const days = within(hours).getByRole("group", { name: /Рабочие дни/ });
    expect(within(days).getByRole("checkbox", { name: "Пн" })).toBeChecked();
    expect(within(days).getByRole("checkbox", { name: "Сб" })).not.toBeChecked();
    fireEvent.click(within(days).getByRole("checkbox", { name: "Сб" }));
    expect(await within(hours).findByText("Есть несохранённые изменения")).toBeVisible();
    fireEvent.click(within(hours).getByRole("button", { name: /Сохранить/ }));
    expect(await screen.findByText("Настройки «Рабочие часы» сохранены")).toBeVisible();
  });

  it("правила передачи: пробный прогон считает на значениях из формы и ничего не сохраняет", async () => {
    await openPage("admin@demo.example", "/admin/timing", "Время и сроки");
    await form("Правила передачи");
    const dry = await screen.findByRole("region", { name: "Пробный прогон правил передачи" });
    fireEvent.click(
      within(dry).getByRole("button", { name: /Проверить на последних 50 диалогах/ }),
    );
    const first = await within(dry).findByRole("status", { name: "Итог пробного прогона" });
    expect(within(first).getByText("Передач сейчас").nextSibling).toHaveTextContent("12");
    expect(within(first).getByText("Передач с новыми правилами").nextSibling).toHaveTextContent(
      "12",
    );
    expect(within(first).getByText(/Изменится: 0/)).toBeVisible();

    fireEvent.change(screen.getByLabelText("Оценка лида для передачи"), {
      target: { value: "55" },
    });
    fireEvent.click(
      await within(dry).findByRole("button", { name: /Проверить на последних 50 диалогах/ }),
    );
    await waitFor(() => {
      const result = within(dry).getByRole("status", { name: "Итог пробного прогона" });
      expect(within(result).getByText("Передач с новыми правилами").nextSibling).toHaveTextContent(
        "15",
      );
    });
    expect(within(dry).getByText(/Изменится у лидов: 2/)).toBeVisible();
    expect(
      within(await form("Правила передачи")).getByText("Есть несохранённые изменения"),
    ).toBeVisible();
  });

  it("несохранённые изменения: уход со страницы спрашивает «Выйти без сохранения?», «Остаться» оставляет форму", async () => {
    await openPage("admin@demo.example", "/admin/timing", "Время и сроки");
    const hours = await form("Рабочие часы");
    fireEvent.click(
      within(await within(hours).findByRole("group", { name: /Рабочие дни/ })).getByRole(
        "checkbox",
        { name: "Сб" },
      ),
    );
    const menu = screen.getByRole("navigation", { name: "Разделы модуля" });
    fireEvent.click(within(menu).getByRole("link", { name: "Журнал" }));
    expect(
      await screen.findByRole("dialog", { name: "Выйти без сохранения?" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Остаться" }));
    expect(within(hours).getByText("Есть несохранённые изменения")).toBeVisible();

    fireEvent.click(within(menu).getByRole("link", { name: "Журнал" }));
    const leave = await screen.findAllByRole("button", { name: "Выйти без сохранения" });
    fireEvent.click(leave[leave.length - 1] as HTMLElement);
    expect(await screen.findByRole("heading", { level: 1, name: "История" })).toBeVisible();
  });
});

describe("Настройки · Telegram: тексты", () => {
  it("группы с таблицей «название · ru · uz · en», поиск по названию и по ситуации", async () => {
    await openTelegram("admin@demo.example", "?tab=texts");

    expect(await screen.findByRole("heading", { level: 2, name: "Тексты бота" })).toBeVisible();
    expect(await screen.findByText(/Приветствие и согласие · /)).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "Русский" })).toBeVisible();
    expect(screen.getByText("Приветствие")).toBeVisible();

    fireEvent.change(
      screen.getByRole("searchbox", { name: "Найти текст по названию или ситуации" }),
      {
        target: { value: "нерабочее" },
      },
    );
    expect(await screen.findByText("Передача менеджеру (нерабочее время)")).toBeInTheDocument();
    expect(screen.queryByText("Приветствие")).toBeNull();
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Найти текст по названию или ситуации" }),
      {
        target: { value: "ничего-такого" },
      },
    );
    expect(await screen.findByText("Ничего не найдено: измените запрос.")).toBeVisible();
  });

  it("правка текста в боковом окне: три языка, предпросмотр подстановок, без «Что произойдёт», сохранение раздела", async () => {
    await openTelegram("admin@demo.example", "?tab=texts");

    fireEvent.click(await screen.findByRole("button", { name: "Изменить: Приветствие" }));
    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { level: 3, name: "Приветствие" }),
    ).toBeVisible();
    expect(within(panel).queryByRole("group", { name: "Что произойдёт" })).toBeNull();
    const ru = within(panel).getByLabelText("Приветствие · Русский");
    fireEvent.change(ru, { target: { value: "Здравствуйте! Вас приветствует {company}." } });
    expect(
      await within(panel).findByText(
        /Предпросмотр: Здравствуйте! Вас приветствует RailTech \(демо\)\./,
      ),
    ).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Сохранить раздел" }));
    expect(await screen.findByText("Настройки «Тексты бота» сохранены")).toBeVisible();
  });

  it("пустой перевод: CRM называет путь, панель открывается на нём, исправление сохраняется", async () => {
    await openTelegram("admin@demo.example", "?tab=texts");

    fireEvent.click(await screen.findByRole("button", { name: "Изменить: Приветствие" }));
    const panel = await panelEl();
    fireEvent.change(await within(panel).findByLabelText("Приветствие · Узбекский"), {
      target: { value: "" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Сохранить раздел" }));

    expect(await within(panel).findAllByText("Нет перевода")).not.toHaveLength(0);
    fireEvent.change(within(panel).getByLabelText("Приветствие · Узбекский"), {
      target: { value: "Salom!" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Сохранить раздел" }));
    expect(await screen.findByText("Настройки «Тексты бота» сохранены")).toBeVisible();
  });
});

describe("Настройки · Telegram: шаблоны ответов", () => {
  it("список, создание без «Что произойдёт», правка и удаление (удаление — с ним)", async () => {
    await openTelegram("admin@demo.example", "?tab=templates");

    expect(await screen.findByRole("heading", { level: 2, name: "Шаблоны ответов" })).toBeVisible();
    expect(
      await screen.findByRole("link", { name: "Открыть шаблон: Пришлю КП сегодня" }),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("link", { name: "Новый шаблон" }));
    let panel = await panelEl();
    const form = await within(panel).findByRole("form", { name: "Новый шаблон" });
    expect(within(form).queryByRole("group", { name: "Что произойдёт" })).toBeNull();
    expect(within(form).getByRole("button", { name: "Создать шаблон" })).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Название"), {
      target: { value: "Скидка по запросу" },
    });
    fireEvent.change(within(form).getByLabelText("Текст — Русский"), {
      target: { value: "{name}, скидку согласует {manager}." },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Создать шаблон" }));
    expect(await screen.findByText("Шаблон создан")).toBeVisible();
    expect(
      await screen.findByRole("link", { name: "Открыть шаблон: Скидка по запросу" }),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("link", { name: "Открыть шаблон: Спасибо за обращение" }));
    panel = await panelEl();
    const edit = await within(panel).findByRole("form", { name: "Изменить шаблон" });
    fireEvent.change(within(edit).getByLabelText("Название"), {
      target: { value: "Благодарность" },
    });
    fireEvent.click(within(edit).getByRole("button", { name: "Сохранить шаблон" }));
    expect(await screen.findByText("Шаблон сохранён")).toBeVisible();
    expect(
      await screen.findByRole("link", { name: "Открыть шаблон: Благодарность" }),
    ).toBeVisible();

    fireEvent.click(await within(await panelEl()).findByRole("button", { name: "Удалить шаблон" }));
    const remove = within(await panelEl()).getByRole("form", { name: "Удалить шаблон" });
    fireEvent.click(within(remove).getByRole("button", { name: "Удалить шаблон" }));
    expect(await screen.findByText("Шаблон удалён")).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("link", { name: "Открыть шаблон: Благодарность" })).toBeNull();
    });
  });

  it("неизвестная подстановка отклоняется CRM — сообщение на экране", async () => {
    await openTelegram("admin@demo.example", "?tab=templates&template=new&panel=open");
    const form = await within(await panelEl()).findByRole("form", { name: "Новый шаблон" });

    fireEvent.change(within(form).getByLabelText("Название"), { target: { value: "Ошибка" } });
    fireEvent.change(within(form).getByLabelText("Текст — Русский"), {
      target: { value: "Привет, {fio}" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Создать шаблон" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent("Значения не приняты");
  });
});

describe("Настройки · Система · Выгрузки CSV", () => {
  function stubDownload() {
    const saved: string[] = [];
    URL.createObjectURL = vi.fn(() => "blob:test");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved.push(this.download);
    });
    return saved;
  }

  it("администратор без второй роли: кнопки недоступны, причина названа — нужен раздел данных", async () => {
    await openPage("admin@demo.example", "/admin/exports", "Выгрузки");

    expect(await screen.findByRole("heading", { level: 2, name: "Выгрузки CSV" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Скачать: Сделки" })).toBeDisabled();
    expect(screen.getByText(/нужен раздел «Клиенты · Клиенты»/)).toBeVisible();
    // выгружаются только сделки, без контактов (решение владельца 2026-11-11)
    expect(screen.queryByRole("heading", { level: 3, name: "Лиды" })).toBeNull();
    expect(screen.queryByRole("heading", { level: 3, name: "Клиенты" })).toBeNull();
  });

  it("роль с данными: файл скачивается под именем с датой, фильтры уходят в запрос", async () => {
    const saved = stubDownload();
    await openPage("all@demo.example", "/admin/exports", "Выгрузки");

    const deals = (await screen.findByRole("heading", { level: 3, name: "Сделки" })).closest(
      "article",
    );
    if (!deals) throw new Error("нет карточки сделок");
    fireEvent.click(within(deals).getByRole("button", { name: /Скачать: Сделки/ }));
    expect(await screen.findByText("Файл «deals-20261026-1430.csv» скачан")).toBeVisible();
    expect(saved).toContain("deals-20261026-1430.csv");
    vi.restoreAllMocks();
  });

  it("директор видит выгрузки без права скачивать", async () => {
    await openPage("director@demo.example", "/admin/exports", "Выгрузки");

    expect(
      await screen.findByText("Только просмотр: выгружает данные администратор."),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Скачать: Сделки" })).toBeDisabled();
  });
});

describe("Admin · Настройки бота: права", () => {
  it("директор: разделы читает, кнопок изменения нет, поля заблокированы", async () => {
    const { router } = await openPage("director@demo.example", "/admin/timing", "Время и сроки");
    const hours = await form("Рабочие часы");
    expect(screen.getByText("Только просмотр")).toBeVisible();
    expect(within(hours).queryByRole("button", { name: /Сохранить/ })).toBeNull();
    expect(screen.queryByRole("group", { name: "Что произойдёт" })).toBeNull();
    expect(await within(hours).findByLabelText("Начало рабочего дня")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Проверить на последних 50 диалогах/ })).toBeNull();
    router.dispose();

    await openTelegram("director@demo.example", "?tab=templates");
    expect(screen.queryByRole("link", { name: "Новый шаблон" })).toBeNull();
    expect(
      await screen.findByRole("link", { name: "Открыть шаблон: Пришлю КП сегодня" }),
    ).toBeVisible();
  });

  it("менеджер: пункта «Telegram» в меню нет, по прямому адресу — «Нет доступа»; старый адрес бота уводит туда же", async () => {
    signIn("manager@demo.example");
    renderAt("/admin/bot");

    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Telegram" })).toBeNull();
    expect(screen.queryByRole("tablist", { name: "Разделы Telegram-бота" })).toBeNull();
  });
});
