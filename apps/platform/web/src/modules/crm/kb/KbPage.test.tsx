import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { endSession } from "../../../mocks/mockSession";
import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";

setupBotTests();

async function openKb(email: string, search = "") {
  signIn(email);
  const view = renderAt(`/crm/kb${search}`);
  expect(await screen.findByRole("heading", { level: 1, name: "База знаний бота" })).toBeVisible();
  return view;
}

function row(title: string): HTMLElement {
  const link = screen.getByRole("link", { name: `Открыть документ: ${title}` });
  const tr = link.closest("tr");
  if (!tr) throw new Error(`нет строки ${title}`);
  return tr;
}

describe("CRM · База знаний: документы", () => {
  it("администратор: документы со статусом индексации словом, кнопки загрузки, песочница во вкладках", async () => {
    await openKb("admin@demo.example");

    expect(await screen.findByRole("heading", { level: 2, name: "Документы" })).toBeVisible();
    expect(within(row("Сроки и условия поставки")).getByText("Готов")).toBeVisible();
    expect(within(row("Warranty and returns")).getByText("Обрабатывается")).toBeVisible();
    expect(within(row("Прайс-лист (черновик)")).getByText("Ошибка")).toBeVisible();
    expect(within(row("Устаревший регламент отгрузки")).getByText("Выключен")).toBeVisible();
    expect(screen.getByRole("link", { name: "Загрузить файл" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Добавить вручную" })).toBeVisible();
    const views = screen.getByRole("radiogroup", { name: "Раздел базы знаний" });
    expect(within(views).getByText("Песочница бота")).toBeVisible();
    expect(screen.queryByText("Только просмотр")).toBeNull();
  });

  it("менеджер: читает и ищет, но без кнопок изменения и без песочницы", async () => {
    await openKb("manager@demo.example");

    expect(await screen.findByRole("heading", { level: 2, name: "Документы" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Загрузить файл" })).toBeNull();
    expect(screen.getByText("Только просмотр")).toBeVisible();
    const views = screen.getByRole("radiogroup", { name: "Раздел базы знаний" });
    expect(within(views).queryByText("Песочница бота")).toBeNull();
    expect(within(views).getByText("Пробелы")).toBeVisible();
  });

  it("директор читает базу знаний через раздел «Все лиды» только для чтения", async () => {
    await openKb("director@demo.example");

    expect(await screen.findByRole("heading", { level: 2, name: "Документы" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Загрузить файл" })).toBeNull();
  });

  it("«Что найдёт бот»: уверенный ответ с фрагментом и порогом; без совпадения — «не знаю»", async () => {
    await openKb("manager@demo.example");
    const query = await screen.findByLabelText("Вопрос клиента");

    fireEvent.change(query, { target: { value: "Какие сроки поставки?" } });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));
    expect(await screen.findByText("Бот ответит по базе знаний")).toBeVisible();
    expect(screen.getByText("Лучшее совпадение: 0.83, порог: 0.70")).toBeVisible();
    const hits = screen.getByRole("list", { name: "Найденные фрагменты" });
    expect(within(hits).getAllByText("Сроки и условия поставки")[0]).toBeVisible();

    fireEvent.change(query, { target: { value: "Расскажите про погоду" } });
    fireEvent.click(await screen.findByRole("button", { name: /Найти/ }));
    expect(await screen.findByText("Бот скажет «не знаю» и предложит менеджера")).toBeVisible();
    expect(screen.getByText("Ничего не найдено.")).toBeVisible();
  });

  it("поиск без ключа эмбеддингов — словами и с подсказкой, куда идти (C2A-G-6)", async () => {
    await openKb("admin@demo.example");

    fireEvent.change(await screen.findByLabelText("Вопрос клиента"), {
      target: { value: "поиск без ключа" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));

    expect(
      await screen.findByText(
        "Модель поиска недоступна: добавьте ключ эмбеддингов в Настройках · Подключения, раздел «Модели ИИ», и повторите.",
      ),
    ).toBeVisible();
  });

  it("карточка документа в боковом окне: реквизиты, фрагменты, «Что произойдёт» перед выключением", async () => {
    await openKb("admin@demo.example");

    fireEvent.click(
      await screen.findByRole("link", { name: "Открыть документ: Сроки и условия поставки" }),
    );
    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { level: 3, name: "Сроки и условия поставки" }),
    ).toBeVisible();
    expect(await within(panel).findByText("Фрагмент 1")).toBeVisible();
    expect(within(panel).getByText("rails")).toBeVisible();

    fireEvent.click(within(panel).getByRole("button", { name: "Выключить документ" }));
    const form = within(panel).getByRole("form", { name: "Выключить документ" });
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    fireEvent.click(within(form).getByRole("button", { name: "Выключить документ" }));

    expect(await screen.findByText("Документ выключен")).toBeVisible();
    await waitFor(() => {
      expect(within(row("Сроки и условия поставки")).getByText("Выключен")).toBeVisible();
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Включить документ" }));
    fireEvent.click(
      within(within(panel).getByRole("form", { name: "Включить документ" })).getByRole("button", {
        name: "Включить документ",
      }),
    );
    await waitFor(() => {
      expect(within(row("Сроки и условия поставки")).queryByText("Выключен")).toBeNull();
    });
  });

  it("переиндексация: «Что произойдёт», статус «В очереди»; идущую индексацию CRM не даёт повторить", async () => {
    await openKb("admin@demo.example");

    fireEvent.click(
      await screen.findByRole("link", { name: "Открыть документ: Гарантия на продукцию" }),
    );
    const panel = await panelEl();
    fireEvent.click(await within(panel).findByRole("button", { name: "Переиндексировать" }));
    const form = within(panel).getByRole("form", { name: "Переиндексировать" });
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    fireEvent.click(within(form).getByRole("button", { name: "Переиндексировать документ" }));
    expect(await screen.findByText("Документ поставлен на переиндексацию")).toBeVisible();
    await waitFor(() => {
      expect(within(row("Гарантия на продукцию")).getByText("В очереди")).toBeVisible();
    });

    fireEvent.click(screen.getByRole("link", { name: "Открыть документ: Warranty and returns" }));
    const busy = await within(await panelEl()).findByRole("button", { name: "Переиндексировать" });
    fireEvent.click(busy);
    fireEvent.click(
      within(within(await panelEl()).getByRole("form", { name: "Переиндексировать" })).getByRole(
        "button",
        { name: "Переиндексировать документ" },
      ),
    );
    expect(
      await screen.findByText(
        "Документ уже стоит в очереди на индексацию или индексируется. Подождите минуту и повторите.",
      ),
    ).toBeVisible();
  });

  it("менеджер видит карточку документа без действий", async () => {
    await openKb("manager@demo.example", "?doc=1&panel=open");

    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { level: 3, name: "Сроки и условия поставки" }),
    ).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Выключить документ" })).toBeNull();
    expect(
      within(panel).getByText("Только просмотр: изменения вносит администратор."),
    ).toBeVisible();
  });
});

describe("CRM · База знаний: загрузка и ручной ввод", () => {
  function chooseFile(name: string, content = "---\ntitle: FAQ\n---\n# FAQ\n") {
    const input = screen.getByLabelText("Файл .md");
    const file = new File([content], name, { type: "text/markdown" });
    fireEvent.change(input, { target: { files: [file] } });
    return file;
  }

  it("файл .md: название берётся из имени, «Что произойдёт», документ появляется в очереди", async () => {
    await openKb("admin@demo.example");

    fireEvent.click(await screen.findByRole("link", { name: "Загрузить файл" }));
    const panel = await panelEl();
    const form = await within(panel).findByRole("form", { name: "Загрузить файл Markdown" });
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    expect(within(form).getByRole("button", { name: "Загрузить документ" })).toBeDisabled();

    chooseFile("faq-oplata.md");
    expect(await within(form).findByDisplayValue("faq-oplata")).toBeVisible();
    fireEvent.click(within(form).getByRole("button", { name: "Загрузить документ" }));

    expect(
      await screen.findByText("Документ добавлен — индексация займёт до минуты"),
    ).toBeVisible();
    expect(await screen.findByRole("heading", { level: 3, name: "faq-oplata" })).toBeVisible();
    await waitFor(() => {
      expect(within(row("faq-oplata")).getByText("В очереди")).toBeVisible();
    });
  });

  it("не .md, пустой и слишком большой файл отклоняются на экране, кнопка недоступна", async () => {
    await openKb("admin@demo.example", "?new=upload&panel=open");
    const panel = await panelEl();
    const form = await within(panel).findByRole("form", { name: "Загрузить файл Markdown" });

    chooseFile("price.pdf");
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Принимаются только файлы Markdown (.md).",
    );
    expect(within(form).getByRole("button", { name: "Загрузить документ" })).toBeDisabled();

    chooseFile("empty.md", "");
    expect(await within(form).findByText("Файл пустой.")).toBeVisible();

    const big = new File(["x"], "big.md");
    Object.defineProperty(big, "size", { value: 26 * 1024 * 1024 });
    fireEvent.change(screen.getByLabelText("Файл .md"), { target: { files: [big] } });
    expect(await within(form).findByText("Файл больше 25 МБ.")).toBeVisible();
  });

  it("нарушение формата: CRM называет правило, текст «что исправить» — на языке сотрудника", async () => {
    await openKb("admin@demo.example", "?new=upload&panel=open");
    const form = await within(await panelEl()).findByRole("form", {
      name: "Загрузить файл Markdown",
    });

    chooseFile("bad-format.md");
    fireEvent.change(await within(form).findByLabelText("Название"), {
      target: { value: "Прайс" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Загрузить документ" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Файл не по формату базы знаний: В начале файла нет front matter",
    );
  });

  it("ручной ввод: название, текст, продукт из справочника (менеджер+админ) — документ создан", async () => {
    await openKb("all@demo.example");

    fireEvent.click(await screen.findByRole("link", { name: "Добавить вручную" }));
    const form = await within(await panelEl()).findByRole("form", {
      name: "Добавить документ вручную",
    });
    fireEvent.change(within(form).getByLabelText("Название"), { target: { value: "Рассрочка" } });
    fireEvent.change(within(form).getByLabelText("Текст документа (Markdown)"), {
      target: { value: "## Рассрочка\n\nПредоставляется по договору." },
    });
    expect(within(form).getByRole("combobox", { name: "Продукт" })).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Добавить документ" }));

    expect(
      await screen.findByText("Документ добавлен — индексация займёт до минуты"),
    ).toBeVisible();
    await waitFor(() => {
      expect(within(row("Рассрочка")).getByText("В очереди")).toBeVisible();
    });
  });

  it("администратор без второй роли: справочник продуктов недоступен — ключ вводится вручную, чужой ключ отклоняет CRM", async () => {
    await openKb("admin@demo.example", "?new=manual&panel=open");
    const form = await within(await panelEl()).findByRole("form", {
      name: "Добавить документ вручную",
    });

    fireEvent.change(within(form).getByLabelText("Название"), { target: { value: "Условия" } });
    fireEvent.change(within(form).getByLabelText("Текст документа (Markdown)"), {
      target: { value: "Текст" },
    });
    const product = await within(form).findByLabelText("Продукт");
    expect(product.tagName).toBe("INPUT");
    fireEvent.change(product, { target: { value: "no-such" } });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить документ" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Такого продукта нет в справочнике.",
    );
  });
});

describe("CRM · База знаний: пробелы", () => {
  it("открытые пробелы: частые выше, язык и совпадение; вкладки «Закрытые» и «Игнорируемые»", async () => {
    await openKb("manager@demo.example", "?view=gaps");

    expect(
      await screen.findByRole("heading", { level: 2, name: "Пробелы базы знаний" }),
    ).toBeVisible();
    const rows = await screen.findAllByRole("link", { name: /^Открыть пробел:/ });
    expect(rows.map((r) => r.textContent)).toEqual([
      "Есть ли гарантия на крепёж?",
      "Qanday to‘lov usullari bor?",
      "Можно ли оплатить частями?",
      "Do you deliver to Samarkand?",
    ]);
    expect(screen.getByRole("link", { name: "L-2041" })).toHaveAttribute(
      "href",
      "/crm/leads/L-2041",
    );

    fireEvent.click(screen.getByText("Закрытые"));
    expect(await screen.findByRole("link", { name: /Какой минимальный заказ/ })).toBeVisible();
    fireEvent.click(screen.getByText("Игнорируемые"));
    expect(await screen.findByRole("link", { name: /Расскажите анекдот/ })).toBeVisible();
  });

  it("администратор: создать документ из вопроса закрывает пробел", async () => {
    await openKb("admin@demo.example", "?view=gaps");

    fireEvent.click(
      await screen.findByRole("link", { name: "Открыть пробел: Есть ли гарантия на крепёж?" }),
    );
    const panel = await panelEl();
    fireEvent.click(
      await within(panel).findByRole("button", { name: "Создать документ из вопроса" }),
    );
    const form = within(panel).getByRole("form", { name: "Добавить документ вручную" });
    expect(within(form).getByLabelText("Название")).toHaveValue("Есть ли гарантия на крепёж?");
    expect(within(form).getByText(/пробел, из которого он создан, закроется/)).toBeVisible();
    fireEvent.change(within(form).getByLabelText("Текст документа (Markdown)"), {
      target: { value: "## Гарантия на крепёж\n\n12 месяцев." },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить документ" }));

    expect(
      await screen.findByText("Документ добавлен, пробел закрыт — индексация займёт до минуты"),
    ).toBeVisible();
    expect(await screen.findByRole("heading", { level: 2, name: "Документы" })).toBeVisible();
    fireEvent.click(screen.getByRole("radio", { name: "Пробелы" }));
    await screen.findByRole("heading", { level: 2, name: "Пробелы базы знаний" });
    expect(
      screen.queryByRole("link", { name: "Открыть пробел: Есть ли гарантия на крепёж?" }),
    ).toBeNull();
  });

  it("привязать к готовому документу, игнорировать и вернуть — каждое с «Что произойдёт»", async () => {
    await openKb("admin@demo.example", "?view=gaps");

    fireEvent.click(
      await screen.findByRole("link", { name: "Открыть пробел: Можно ли оплатить частями?" }),
    );
    let panel = await panelEl();
    fireEvent.click(await within(panel).findByRole("button", { name: "Привязать к документу" }));
    const link = within(panel).getByRole("form", { name: "Привязать к документу" });
    expect(within(link).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    expect(within(link).getByRole("button", { name: "Привязать и закрыть пробел" })).toBeDisabled();
    fireEvent.mouseDown(within(link).getByRole("combobox", { name: "Документ с ответом" }));
    fireEvent.click(await screen.findByText("Гарантия на продукцию"));
    fireEvent.click(within(link).getByRole("button", { name: "Привязать и закрыть пробел" }));
    expect(await screen.findByText("Пробел закрыт")).toBeVisible();
    await waitFor(() => {
      expect(
        screen.queryByRole("link", { name: "Открыть пробел: Можно ли оплатить частями?" }),
      ).toBeNull();
    });

    fireEvent.click(
      screen.getByRole("link", { name: "Открыть пробел: Do you deliver to Samarkand?" }),
    );
    panel = await panelEl();
    fireEvent.click(await within(panel).findByRole("button", { name: "Игнорировать" }));
    const ignore = within(panel).getByRole("form", { name: "Игнорировать" });
    expect(within(ignore).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    fireEvent.click(within(ignore).getByRole("button", { name: "Игнорировать пробел" }));
    expect(await screen.findByText("Пробел скрыт")).toBeVisible();

    fireEvent.click(screen.getByText("Игнорируемые"));
    fireEvent.click(
      await screen.findByRole("link", { name: "Открыть пробел: Do you deliver to Samarkand?" }),
    );
    panel = await panelEl();
    fireEvent.click(await within(panel).findByRole("button", { name: "Вернуть в открытые" }));
    fireEvent.click(
      within(within(panel).getByRole("form", { name: "Вернуть в открытые" })).getByRole("button", {
        name: "Вернуть пробел",
      }),
    );
    expect(await screen.findByText("Пробел возвращён в открытые")).toBeVisible();
  });

  it("менеджер видит карточку пробела без действий", async () => {
    await openKb("manager@demo.example", "?view=gaps&gap=1&panel=open");

    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { level: 3, name: "Есть ли гарантия на крепёж?" }),
    ).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Игнорировать" })).toBeNull();
  });
});

describe("CRM · База знаний: песочница", () => {
  it("диалог с ботом: ответ с кнопками и «Почему так»; передача менеджеру только показывается; «Начать заново»", async () => {
    await openKb("admin@demo.example", "?view=sandbox");

    expect(await screen.findByRole("heading", { level: 2, name: "Песочница бота" })).toBeVisible();
    expect(screen.getByText("Платно: ответы считаются в «Расходах» как тест.")).toBeVisible();
    const input = screen.getByLabelText("Вопрос клиента");
    fireEvent.change(input, { target: { value: "Какие сроки поставки рельсов?" } });
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Отправить боту/ }));

    const log = await screen.findByRole("log", { name: "Диалог с ботом" });
    expect(await within(log).findByText(/Срок поставки рельсов — от 14 дней/)).toBeVisible();
    expect(within(log).getByText("Передать менеджеру")).toBeVisible();
    fireEvent.click(within(log).getByText("Почему бот ответил так"));
    expect(within(log).getByText("ответ по базе знаний")).toBeVisible();
    expect(within(log).getByText("Сроки и условия поставки")).toBeVisible();

    fireEvent.change(input, { target: { value: "Сколько стоит доставка?" } });
    fireEvent.click(await screen.findByRole("button", { name: /Отправить боту/ }));
    expect(await within(log).findByText(/Передаю ваш вопрос менеджеру/)).toBeVisible();
    fireEvent.click(within(log).getAllByText("Почему бот ответил так")[1] as HTMLElement);
    expect(within(log).getByText("передача менеджеру")).toBeVisible();
    expect(within(log).getByText("Цена или условия — нет в базе")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Начать заново" }));
    const reset = screen.getByRole("form", { name: "Начать заново" });
    expect(within(reset).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    fireEvent.click(within(reset).getByRole("button", { name: "Очистить диалог" }));
    await waitFor(() => {
      expect(screen.queryByRole("log")).toBeNull();
    });
    expect(screen.getByText(/Задайте вопрос, который часто задают клиенты/)).toBeVisible();
  });

  it("сбой модели в песочнице — словами, диалог остаётся", async () => {
    await openKb("admin@demo.example", "?view=sandbox");

    fireEvent.change(await screen.findByLabelText("Вопрос клиента"), {
      target: { value: "сбой модели" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Отправить боту/ }));

    expect(
      await screen.findByText(
        "Шлюз моделей не отвечает: бот не может сформировать ответ. Повторите позже.",
      ),
    ).toBeVisible();
  });

  it("менеджер по прямой ссылке на песочницу попадает на документы", async () => {
    await openKb("manager@demo.example", "?view=sandbox");

    expect(await screen.findByRole("heading", { level: 2, name: "Документы" })).toBeVisible();
    expect(screen.queryByRole("heading", { level: 2, name: "Песочница бота" })).toBeNull();
  });
});

describe("CRM · База знаний: пункт меню и права", () => {
  it("снабженцу пункта «База знаний» в меню CRM нет, по прямому адресу — «Нет доступа»", async () => {
    signIn("supply@demo.example");
    renderAt("/crm/clients");
    expect(await screen.findByRole("heading", { level: 1, name: "Клиенты" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "База знаний бота" })).toBeNull();
    cleanup();

    renderAt("/crm/kb");
    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
  });

  it("администратор без лидов видит в CRM единственный пункт — «База знаний»; менеджер — вместе с остальными", async () => {
    signIn("admin@demo.example");
    renderAt("/crm/kb");
    const menu = await screen.findByRole("link", { name: "База знаний бота" });
    expect(menu).toBeVisible();
    expect(screen.queryByRole("link", { name: "Лиды" })).toBeNull();
    cleanup();
    endSession();

    signIn("manager@demo.example");
    renderAt("/crm/kb");
    expect(await screen.findByRole("link", { name: "База знаний бота" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Лиды" })).toBeVisible();
  });
});
