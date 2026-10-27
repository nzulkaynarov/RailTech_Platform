import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";

setupBotTests();

/** Без адреса раздела — вкладка «Поведение и передача» (W15-H4: у бота вкладки; первая — «Подключение»). */
async function openBot(email: string, search = "?part=behavior") {
  signIn(email);
  const view = renderAt(`/admin/bot${search}`);
  expect(await screen.findByRole("heading", { level: 1, name: "Telegram-бот" })).toBeVisible();
  await screen.findByRole("tablist", { name: "Разделы Telegram-бота" });
  return view;
}

function tab(name: string) {
  fireEvent.click(
    within(screen.getByRole("tablist", { name: "Разделы Telegram-бота" })).getByRole("tab", {
      name,
    }),
  );
}

function nav() {
  return screen.getByRole("navigation", { name: "Разделы настроек бота" });
}

async function section(name: string) {
  fireEvent.click(within(nav()).getByRole("link", { name }));
  return screen.findByRole("heading", { level: 2, name });
}

describe("Admin · Настройки бота: разделы", () => {
  it("бот в одном месте (W15-H4): вкладки «Подключение · Тексты · Поведение и передача · База знаний · Шаблоны ответов · Выгрузки»", async () => {
    await openBot("admin@demo.example", "");
    const tabs = screen.getByRole("tablist", { name: "Разделы Telegram-бота" });
    expect(
      within(tabs)
        .getAllByRole("tab")
        .map((t) => t.textContent),
    ).toEqual([
      "Подключение",
      "Тексты",
      "Поведение и передача",
      "База знаний",
      "Шаблоны ответов",
      "Выгрузки",
    ]);
    // по умолчанию — «Подключение»: токен, канал команды и профиль, раньше бывшие в «Подключениях»
    expect(within(tabs).getByRole("tab", { name: "Подключение" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(await screen.findByText("@demo_railtech_bot")).toBeVisible();
    expect(screen.getByRole("button", { name: "Сменить токен" })).toBeVisible();

    tab("База знаний");
    expect(await screen.findByRole("link", { name: "Открыть базу знаний" })).toHaveAttribute(
      "href",
      "/crm/kb",
    );
    expect(await screen.findByText("Минимальное сходство, чтобы бот отвечал (0–1)")).toBeVisible();
  });

  it("администратор: разделы «Поведения и передачи» по группам; открывается «Компания» со значениями CRM", async () => {
    await openBot("admin@demo.example");

    expect(await screen.findByRole("heading", { level: 2, name: "Компания" })).toBeVisible();
    const links = within(nav())
      .getAllByRole("link")
      .map((l) => l.textContent);
    expect(links).toEqual([
      "Компания",
      "Рабочие часы",
      "Поведение бота",
      "Стоп-слова",
      "Конкуренты",
      "Правила передачи",
      "Квалификация",
      "Форма «Заявка» с сайта",
      "Канал команды",
      "Оповещения о сбоях сервисов",
      "Сделки",
      "Бюджет моделей",
    ]);
    expect(screen.getByLabelText("Название компании")).toHaveValue("RailTech (демо)");
    expect(
      screen.getByLabelText("Телефон компании (бот называет его по просьбе клиента)"),
    ).toHaveValue("+998 71 000 00 00");
    expect(within(nav()).getByRole("link", { name: "Компания" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    expect(screen.getByText("Изменений нет")).toBeVisible();
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
  });

  it("сохранение раздела: «Есть несохранённые изменения», «Что произойдёт», сообщение; «Отменить изменения» возвращает значения", async () => {
    await openBot("admin@demo.example");
    const name = await screen.findByLabelText("Название компании");

    fireEvent.change(name, { target: { value: "RailTech Групп (демо)" } });
    expect(await screen.findByText("Есть несохранённые изменения")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Отменить изменения" }));
    await waitFor(() => {
      expect(screen.getByLabelText("Название компании")).toHaveValue("RailTech (демо)");
    });
    expect(screen.getByText("Изменений нет")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Название компании"), {
      target: { value: "RailTech Групп (демо)" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Сохранить/ }));
    expect(await screen.findByText("Настройки «Компания» сохранены")).toBeVisible();
    await waitFor(() => {
      expect(screen.getByText("Изменений нет")).toBeVisible();
    });
    expect(screen.getByLabelText("Название компании")).toHaveValue("RailTech Групп (демо)");

    // после перезагрузки экрана новое значение приходит из CRM
    await section("Рабочие часы");
    await section("Компания");
    expect(await screen.findByLabelText("Название компании")).toHaveValue("RailTech Групп (демо)");
  });

  it("CRM не принимает значение: путь поля из ответа подсвечивает поле, сохранить после исправления можно", async () => {
    await openBot("admin@demo.example");
    const name = await screen.findByLabelText("Название компании");

    fireEvent.change(name, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: /Сохранить/ }));

    expect(
      await screen.findByText("CRM не приняла значения: проверьте отмеченные поля."),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Название компании"), {
      target: { value: "Рельсы Демо" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Сохранить/ }));
    expect(await screen.findByText("Настройки «Компания» сохранены")).toBeVisible();
  });

  it("рабочие часы: время, дни недели, праздники и часовой пояс — типизированные поля", async () => {
    await openBot("admin@demo.example", "?section=business_hours");

    expect(await screen.findByRole("heading", { level: 2, name: "Рабочие часы" })).toBeVisible();
    expect(screen.getByLabelText("Начало рабочего дня")).toHaveValue("09:00");
    expect(screen.getByLabelText("Конец рабочего дня")).toHaveValue("18:00");
    const days = screen.getByRole("group", { name: /Рабочие дни/ });
    expect(within(days).getByRole("checkbox", { name: "Пн" })).toBeChecked();
    expect(within(days).getByRole("checkbox", { name: "Сб" })).not.toBeChecked();
    fireEvent.click(within(days).getByRole("checkbox", { name: "Сб" }));
    expect(await screen.findByText("Есть несохранённые изменения")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Сохранить/ }));
    expect(await screen.findByText("Настройки «Рабочие часы» сохранены")).toBeVisible();
  });

  it("поведение бота, стоп-слова, конкуренты, квалификация, веб-форма, оповещения, бюджет и сделки открываются и подписаны на языке сотрудника", async () => {
    await openBot("admin@demo.example");
    const expectations: Record<string, string> = {
      "Поведение бота": "Максимум слов в ответе",
      "Стоп-слова": "Слова",
      Конкуренты: "Слова",
      Квалификация: "Обязательные факты",
      "Форма «Заявка» с сайта": "Минимальное время заполнения формы",
      "Канал команды": "Дежурные",
      "Оповещения о сбоях сервисов": "Личное сообщение админам в Telegram",
      "Бюджет моделей": "Дневной бюджет",
      Сделки: "Причины отказа",
    };
    for (const [name, label] of Object.entries(expectations)) {
      await section(name);
      expect(await screen.findAllByText(label)).not.toHaveLength(0);
    }
    await section("Канал команды");
    expect(screen.queryByLabelText("ID приватного канала")).toBeNull();
    expect(screen.getByRole("link", { name: "Открыть «Подключение»" })).toHaveAttribute(
      "href",
      "/admin/bot?part=connection",
    );
  });

  it("правила передачи: пробный прогон считает на значениях из формы и ничего не сохраняет", async () => {
    await openBot("admin@demo.example", "?section=escalation");

    expect(
      await screen.findByRole("heading", { level: 2, name: "Правила передачи" }),
    ).toBeVisible();
    const dry = screen.getByRole("region", { name: "Пробный прогон правил передачи" });
    expect(within(dry).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
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
    expect(screen.getByText("Есть несохранённые изменения")).toBeVisible();
  });

  it("несохранённые изменения: смена раздела спрашивает «Выйти без сохранения?», «Остаться» оставляет форму", async () => {
    await openBot("admin@demo.example");

    fireEvent.change(await screen.findByLabelText("Название компании"), {
      target: { value: "Иное" },
    });
    fireEvent.click(within(nav()).getByRole("link", { name: "Рабочие часы" }));
    expect(
      await screen.findByRole("dialog", { name: "Выйти без сохранения?" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Остаться" }));
    expect(screen.getByLabelText("Название компании")).toHaveValue("Иное");

    fireEvent.click(within(nav()).getByRole("link", { name: "Рабочие часы" }));
    const leave = await screen.findAllByRole("button", { name: "Выйти без сохранения" });
    fireEvent.click(leave[leave.length - 1] as HTMLElement);
    expect(await screen.findByRole("heading", { level: 2, name: "Рабочие часы" })).toBeVisible();
  });
});

describe("Admin · Настройки бота: тексты", () => {
  it("группы с таблицей «название · ru · uz · en», поиск по названию и по ситуации", async () => {
    await openBot("admin@demo.example", "?section=texts");

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

  it("правка текста в боковом окне: три языка, предпросмотр подстановок, «Что произойдёт», сохранение раздела", async () => {
    await openBot("admin@demo.example", "?section=texts");

    fireEvent.click(await screen.findByRole("button", { name: "Изменить: Приветствие" }));
    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { level: 3, name: "Приветствие" }),
    ).toBeVisible();
    expect(within(panel).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
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
    await openBot("admin@demo.example", "?section=texts");

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

describe("Admin · Настройки бота: шаблоны ответов", () => {
  it("список, создание с «Что произойдёт», правка и удаление", async () => {
    await openBot("admin@demo.example", "?section=templates");

    expect(await screen.findByRole("heading", { level: 2, name: "Шаблоны ответов" })).toBeVisible();
    expect(
      await screen.findByRole("link", { name: "Открыть шаблон: Пришлю КП сегодня" }),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("link", { name: "Новый шаблон" }));
    let panel = await panelEl();
    const form = await within(panel).findByRole("form", { name: "Новый шаблон" });
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
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
    expect(within(remove).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    fireEvent.click(within(remove).getByRole("button", { name: "Удалить шаблон" }));
    expect(await screen.findByText("Шаблон удалён")).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("link", { name: "Открыть шаблон: Благодарность" })).toBeNull();
    });
  });

  it("неизвестная подстановка отклоняется CRM — сообщение на экране", async () => {
    await openBot("admin@demo.example", "?section=templates&template=new&panel=open");
    const form = await within(await panelEl()).findByRole("form", { name: "Новый шаблон" });

    fireEvent.change(within(form).getByLabelText("Название"), { target: { value: "Ошибка" } });
    fireEvent.change(within(form).getByLabelText("Текст — Русский"), {
      target: { value: "Привет, {fio}" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Создать шаблон" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent("CRM не приняла значения");
  });
});

describe("Admin · Настройки бота: выгрузки CSV", () => {
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
    await openBot("admin@demo.example", "?section=exports");

    expect(await screen.findByRole("heading", { level: 2, name: "Выгрузки CSV" })).toBeVisible();
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    for (const title of ["Лиды", "Клиенты", "Сделки"]) {
      expect(screen.getByRole("button", { name: `Скачать: ${title}` })).toBeDisabled();
    }
    expect(screen.getAllByText(/нужен раздел «Клиенты · Лиды»/)).not.toHaveLength(0);
  });

  it("роль с данными: файл скачивается под именем с датой, фильтры уходят в запрос", async () => {
    const saved = stubDownload();
    await openBot("all@demo.example", "?section=exports");

    const leads = (await screen.findByRole("heading", { level: 3, name: "Лиды" })).closest(
      "article",
    );
    if (!leads) throw new Error("нет карточки лидов");
    fireEvent.change(within(leads).getByLabelText("Язык"), { target: { value: "uz" } });
    fireEvent.click(within(leads).getByRole("button", { name: /Скачать: Лиды/ }));
    expect(await screen.findByText("Файл «leads-20261026-1430.csv» скачан")).toBeVisible();
    expect(saved).toContain("leads-20261026-1430.csv");

    const deals = screen.getByRole("heading", { level: 3, name: "Сделки" }).closest("article");
    if (!deals) throw new Error("нет карточки сделок");
    fireEvent.click(within(deals).getByRole("button", { name: /Скачать: Сделки/ }));
    expect(await screen.findByText("Файл «deals-20261026-1430.csv» скачан")).toBeVisible();
    vi.restoreAllMocks();
  });

  it("директор видит выгрузки без права скачивать", async () => {
    await openBot("director@demo.example", "?section=exports");

    expect(
      await screen.findByText("Только просмотр: выгружает данные администратор."),
    ).toBeVisible();
    for (const title of ["Лиды", "Клиенты", "Сделки"]) {
      expect(screen.getByRole("button", { name: `Скачать: ${title}` })).toBeDisabled();
    }
  });
});

describe("Admin · Настройки бота: права", () => {
  it("директор: разделы читает, кнопок изменения нет, поля заблокированы", async () => {
    await openBot("director@demo.example");

    expect(await screen.findByRole("heading", { level: 2, name: "Компания" })).toBeVisible();
    expect(screen.getByText("Только просмотр")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Сохранить/ })).toBeNull();
    expect(screen.queryByRole("group", { name: "Что произойдёт" })).toBeNull();
    expect(screen.getByLabelText("Название компании")).toBeDisabled();
    await section("Правила передачи");
    expect(screen.queryByRole("button", { name: /Проверить на последних 50 диалогах/ })).toBeNull();
    tab("Шаблоны ответов");
    expect(screen.queryByRole("link", { name: "Новый шаблон" })).toBeNull();
    expect(
      await screen.findByRole("link", { name: "Открыть шаблон: Пришлю КП сегодня" }),
    ).toBeVisible();
  });

  it("менеджер: пункта «Настройки бота» в меню Admin нет, по прямому адресу — «Нет доступа»", async () => {
    signIn("manager@demo.example");
    renderAt("/admin/bot");

    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Telegram-бот" })).toBeNull();
    expect(screen.queryByRole("tablist", { name: "Разделы Telegram-бота" })).toBeNull();
  });
});
