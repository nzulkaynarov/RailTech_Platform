import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import {
  clearCompanyArticlesMock,
  readCompanyArticles,
  resetCompanyArticlesMock,
} from "../../../mocks/companyArticlesStore";
import { resetFeedMocks } from "../../../mocks/feedHandlers";
import { endSession, updateSession } from "../../../mocks/mockSession";
import { resetTicketsMock } from "../../../mocks/ticketsStore";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
  resetFeedMocks();
  resetTicketsMock();
  resetCompanyArticlesMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

const heading = () => screen.findByRole("heading", { level: 1, name: "Статьи компании" });

async function rowOf(title: string): Promise<HTMLElement> {
  const button = await screen.findByRole("button", { name: title });
  return button.closest("tr") as HTMLElement;
}

/**
 * Новое окно подтверждения: закрытое antd остаётся в дереве до конца анимации (в jsdom её нет), поэтому ждём окно
 * сверх тех, что уже были, и берём последнее.
 */
async function lastDialog(name: string, before = 0): Promise<HTMLElement> {
  return waitFor(() => {
    const all = screen.queryAllByRole("dialog", { name });
    expect(all.length).toBeGreaterThan(before);
    return all[all.length - 1] as HTMLElement;
  });
}

async function write(title: string, body: string) {
  fireEvent.click(await screen.findByRole("button", { name: "Новая статья" }));
  fireEvent.change(await screen.findByRole("textbox", { name: "Заголовок" }), {
    target: { value: title },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Текст статьи" }), {
    target: { value: body },
  });
}

describe("Настройки · Статьи компании (W18A-P5, B-079)", () => {
  it("администратор видит список со статусами, в том числе черновик; пункт есть в меню Настроек", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    expect(await heading()).toBeInTheDocument();
    expect(document.title).toContain("Статьи компании");
    const contract = await rowOf("Кто согласует договор");
    expect(contract).toHaveTextContent("Опубликовано");
    expect(contract).toHaveTextContent("Русский");
    expect(await rowOf("График отпусков на следующий год")).toHaveTextContent("Черновик");
    expect(screen.getByText(/Всего статей: 3, из них черновиков: 1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Новая статья" })).toBeEnabled();
    expect(screen.getAllByRole("link", { name: "Статьи компании" }).length).toBeGreaterThan(0);
  });

  it("фильтр по статусу: только черновики", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    await rowOf("Кто согласует договор");
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Статус" }));
    const option = await waitFor(() => {
      const found = document.querySelector('.ant-select-item-option[title="Черновик"]');
      expect(found).not.toBeNull();
      return found as Element;
    });
    fireEvent.click(option);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Кто согласует договор" })).toBeNull();
    });
    expect(screen.getByRole("button", { name: "График отпусков на следующий год" })).toBeVisible();
  });

  it("создание: черновик сохраняется, сотрудникам он не виден; предпросмотр показывает разметку", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    await write(
      "Как оформить командировку",
      "## Шаги\n\n- заявка директору\n- билеты через бухгалтера",
    );
    const preview = screen.getByRole("region", { name: "Так статья выглядит в Помощи" });
    expect(
      within(preview).getByRole("heading", { name: "Как оформить командировку" }),
    ).toBeVisible();
    expect(within(preview).getByRole("heading", { name: "Шаги" })).toBeVisible();
    expect(within(preview).getAllByRole("listitem")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Сохранить черновик" }));
    expect(await screen.findByText("Черновик сохранён.")).toBeInTheDocument();
    expect(await rowOf("Как оформить командировку")).toHaveTextContent("Черновик");
    const stored = readCompanyArticles().articles.find(
      (a) => a.title === "Как оформить командировку",
    );
    expect(stored?.status).toBe("draft");
    cleanup();
    endSession();

    signInAs("manager@demo.example");
    renderApp("/help/articles");
    await screen.findByRole("link", { name: "Кто согласует договор" });
    expect(screen.queryByRole("link", { name: "Как оформить командировку" })).toBeNull();
  });

  it("«Сохранить и опубликовать»: сотрудник сразу видит статью в «Как у нас принято»", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    await write("Пропуска на склад", "Заявка на пропуск — за день до визита.");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить и опубликовать" }));
    expect(
      await screen.findByText("Статья опубликована: теперь её видят все сотрудники."),
    ).toBeInTheDocument();
    expect(await rowOf("Пропуска на склад")).toHaveTextContent("Опубликовано");
    cleanup();
    endSession();

    signInAs("manager@demo.example");
    renderApp("/help/articles");
    const company = await screen.findByRole("region", { name: "Как у нас принято" });
    expect(await within(company).findByRole("link", { name: "Пропуска на склад" })).toBeVisible();
  });

  it("пустые заголовок и текст не уходят: ошибки у полей, фокус не теряется", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    fireEvent.click(await screen.findByRole("button", { name: "Новая статья" }));
    fireEvent.click(await screen.findByRole("button", { name: "Сохранить черновик" }));
    expect(await screen.findByText("Напишите заголовок.")).toBeInTheDocument();
    expect(screen.getByText("Напишите текст статьи.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Заголовок" })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(readCompanyArticles().articles).toHaveLength(3);
  });

  it("слишком длинный текст: подсказка до отправки", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    await write("Длинная", "я".repeat(20001));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить черновик" }));
    expect(
      await screen.findByText("Текст длиннее 20000 символов: сократите его."),
    ).toBeInTheDocument();
    expect(readCompanyArticles().articles).toHaveLength(3);
  });

  it("ошибка сервера понятными словами, введённое не пропадает", async () => {
    server.use(
      http.post("*/admin/company-articles", () =>
        HttpResponse.json(
          {
            code: "VALIDATION_FAILED",
            message: "x",
            source: "crm",
            details: { fields: ["title"], reason: "article_title_too_long" },
          },
          { status: 422 },
        ),
      ),
    );
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    await write("Заголовок", "Текст");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить черновик" }));
    expect(
      await screen.findByText("Заголовок длиннее 200 символов: сократите его."),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Текст статьи" })).toHaveValue("Текст");
  });

  it("правка опубликованной статьи видна сотрудникам сразу; кнопка «Сохранить» ждёт изменений", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    const row = await rowOf("Где лежат шаблоны писем");
    fireEvent.click(within(row).getByRole("button", { name: "Править: Где лежат шаблоны писем" }));
    const title = await screen.findByRole("textbox", { name: "Заголовок" });
    expect(title).toHaveValue("Где лежат шаблоны писем");
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    expect(screen.getByText(/Статья уже опубликована/)).toBeInTheDocument();
    fireEvent.change(title, { target: { value: "Где лежат шаблоны" } });
    expect(screen.getByText("Есть несохранённые изменения")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Изменения сохранены.")).toBeInTheDocument();
    expect(await rowOf("Где лежат шаблоны")).toHaveTextContent("Опубликовано");
    expect(readCompanyArticles().articles.find((a) => a.id === 2)?.title).toBe("Где лежат шаблоны");
  });

  it("публикация черновика и снятие с публикации (с подтверждением)", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    const draft = await rowOf("График отпусков на следующий год");
    fireEvent.click(
      within(draft).getByRole("button", { name: "Опубликовать: График отпусков на следующий год" }),
    );
    expect(
      await screen.findByText("Статья опубликована: теперь её видят все сотрудники."),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(readCompanyArticles().articles.find((a) => a.id === 3)?.status).toBe("published");
    });

    const published = await rowOf("График отпусков на следующий год");
    fireEvent.click(
      within(published).getByRole("button", {
        name: "Снять с публикации: График отпусков на следующий год",
      }),
    );
    const dialog = await lastDialog("Снять статью с публикации?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Оставить" }));
    expect(readCompanyArticles().articles.find((a) => a.id === 3)?.status).toBe("published");

    fireEvent.click(
      within(await rowOf("График отпусков на следующий год")).getByRole("button", {
        name: "Снять с публикации: График отпусков на следующий год",
      }),
    );
    const again = await lastDialog("Снять статью с публикации?", 1);
    fireEvent.click(within(again).getByRole("button", { name: "Снять с публикации" }));
    expect(
      await screen.findByText("Статья снята с публикации и снова черновик."),
    ).toBeInTheDocument();
    expect(readCompanyArticles().articles.find((a) => a.id === 3)?.status).toBe("draft");
  });

  it("удаление спрашивает подтверждение: «Не удалять» оставляет, «Удалить» убирает навсегда", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    const row = await rowOf("Где лежат шаблоны писем");
    fireEvent.click(within(row).getByRole("button", { name: "Удалить: Где лежат шаблоны писем" }));
    const dialog = await lastDialog("Удалить статью?");
    expect(dialog).toHaveTextContent("«Где лежат шаблоны писем» будет удалена насовсем");
    fireEvent.click(within(dialog).getByRole("button", { name: "Не удалять" }));
    expect(readCompanyArticles().articles).toHaveLength(3);

    fireEvent.click(
      within(await rowOf("Где лежат шаблоны писем")).getByRole("button", {
        name: "Удалить: Где лежат шаблоны писем",
      }),
    );
    const confirm = await lastDialog("Удалить статью?", 1);
    fireEvent.click(within(confirm).getByRole("button", { name: "Удалить" }));
    expect(await screen.findByText("Статья удалена.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Где лежат шаблоны писем" })).toBeNull();
    });
    expect(readCompanyArticles().articles).toHaveLength(2);
  });

  it("закрыть редактор с несохранённым — вопрос; «Продолжить правку» оставляет текст", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    await write("Черновик на выброс", "Текст");
    fireEvent.click(screen.getByRole("button", { name: "К списку статей" }));
    const dialog = await lastDialog("Закрыть без сохранения?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Продолжить правку" }));
    expect(await screen.findByRole("textbox", { name: "Текст статьи" })).toHaveValue("Текст");

    fireEvent.click(screen.getByRole("button", { name: "К списку статей" }));
    const again = await lastDialog("Закрыть без сохранения?", 1);
    fireEvent.click(within(again).getByRole("button", { name: "Закрыть без сохранения" }));
    expect(await screen.findByRole("button", { name: "Новая статья" })).toBeInTheDocument();
    expect(readCompanyArticles().articles).toHaveLength(3);
  });

  it("опасный текст в редакторе: предпросмотр показывает его текстом, не исполняет", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    await write(
      "Проверка",
      '<script>window.__xss = 1</script>\n\n<img src=x onerror="window.__xss = 2">\n\n[клик](javascript:window.__xss=3)',
    );
    const preview = screen.getByRole("region", { name: "Так статья выглядит в Помощи" });
    expect(preview.querySelector("script, img, a, iframe, svg")).toBeNull();
    expect(within(preview).getByText("<script>window.__xss = 1</script>")).toBeInTheDocument();
    expect(within(preview).getByText(/\[клик\]\(javascript:window\.__xss=3\)/)).toBeInTheDocument();
    expect((window as unknown as { __xss?: number }).__xss).toBeUndefined();
  });

  it("пустой список: приглашение написать первую; ошибка загрузки — повтор", async () => {
    clearCompanyArticlesMock();
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    expect(await screen.findByText("Статей компании пока нет")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Новая статья" }).length).toBeGreaterThan(0);
    cleanup();
    server.use(
      http.get("*/admin/company-articles", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "x", source: "crm" },
          { status: 503 },
        ),
      ),
    );
    renderApp("/admin/articles");
    expect(
      await screen.findByText("Не удалось загрузить статьи", undefined, { timeout: 15_000 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  }, 20_000);

  it("директор читает, в том числе черновик, но не правит: кнопок записи нет, поля только для чтения", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/articles");
    expect(await heading()).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Новая статья" })).toBeNull();
    expect(screen.getByText(/Писать и публиковать их может администратор/)).toBeInTheDocument();
    const draft = await rowOf("График отпусков на следующий год");
    expect(within(draft).queryByRole("button", { name: /Опубликовать/ })).toBeNull();
    expect(within(draft).queryByRole("button", { name: /Удалить/ })).toBeNull();
    fireEvent.click(
      within(draft).getByRole("button", { name: "Открыть: График отпусков на следующий год" }),
    );
    expect(await screen.findByRole("heading", { name: "Статья компании (чтение)" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Заголовок" })).toHaveAttribute("readonly");
    expect(screen.getByRole("textbox", { name: "Текст статьи" })).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Сохранить" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Сохранить и опубликовать" })).toBeNull();
  });

  it("менеджер: раздела нет — «Нет доступа», а адрес ?edit=new записи не открывает", async () => {
    signInAs("manager@demo.example");
    renderApp("/admin/articles?edit=new");
    expect(await screen.findByRole("heading", { name: "Нет доступа" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Текст статьи" })).toBeNull();
  });

  it("директор по адресу ?edit=new не получает редактор записи", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/articles?edit=new");
    expect(await heading()).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Текст статьи" })).toBeNull();
  });

  it("узкий экран: статьи карточками с действиями", async () => {
    setViewportWidth(390);
    signInAs("admin@demo.example");
    renderApp("/admin/articles");
    expect(await heading()).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Статьи компании" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(
      within(list).getByRole("button", { name: "Удалить: Кто согласует договор" }),
    ).toBeVisible();
  });

  it("интерфейс на узбекском и английском", async () => {
    signInAs("admin@demo.example");
    updateSession({ language: "en" });
    renderApp("/admin/articles");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Company articles" }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "New article" })).toBeVisible();
    cleanup();
    updateSession({ language: "uz" });
    renderApp("/admin/articles");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Kompaniya maqolalari" }),
    ).toBeInTheDocument();
  });
});
