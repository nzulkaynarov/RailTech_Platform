import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import {
  clearCompanyArticlesMock,
  readCompanyArticles,
  resetCompanyArticlesMock,
  writeCompanyArticles,
} from "../../mocks/companyArticlesStore";
import { resetFeedMocks } from "../../mocks/feedHandlers";
import { endSession, updateSession } from "../../mocks/mockSession";
import { resetTicketsMock } from "../../mocks/ticketsStore";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";
import { COMPANY_PREFIX, companySlug, isCompanySlug, toHelpArticle } from "./companyArticles";

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

async function openHelp() {
  fireEvent.click(await screen.findByRole("button", { name: "Помощь (клавиша ?)" }));
  return screen.findByRole("dialog", { name: "Помощь" });
}

describe("Статьи компании в Помощи (W18A-P5, B-079)", () => {
  it("/help/articles: «Статьи Платформы» и «Как у нас принято» — опубликованные статьи компании, без черновика", async () => {
    signInAs("manager@demo.example");
    renderApp("/help/articles");
    const company = await screen.findByRole("region", { name: "Как у нас принято" });
    expect(
      await within(company).findByRole("link", { name: "Кто согласует договор" }),
    ).toHaveAttribute("href", "/help/articles/company-1");
    expect(within(company).getByRole("link", { name: "Где лежат шаблоны писем" })).toBeVisible();
    expect(within(company).queryByText(/График отпусков/)).toBeNull();
    const product = screen.getByRole("region", { name: "Статьи Платформы" });
    expect(
      within(product).getByRole("link", { name: "Мои задачи — что сделать сейчас" }),
    ).toBeVisible();
  });

  it("статья компании открывается по адресу: текст, заголовки и списки отрисованы, помечена «Как у нас принято»", async () => {
    signInAs("manager@demo.example");
    renderApp("/help/articles/company-1");
    expect(
      await screen.findByRole("heading", { level: 2, name: "Кто согласует договор" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Порядок согласования" })).toBeInTheDocument();
    expect(screen.getByText(/Юрист проверяет реквизиты/)).toBeInTheDocument();
    expect(screen.getByText(/Как у нас принято · Обновлена/)).toBeInTheDocument();
  });

  it("черновик не открывается по адресу: «Такой статьи нет»; неизвестный номер — то же", async () => {
    signInAs("manager@demo.example");
    renderApp("/help/articles/company-3");
    expect(await screen.findByText("Такой статьи нет")).toBeInTheDocument();
    cleanup();
    renderApp("/help/articles/company-99");
    expect(await screen.findByText("Такой статьи нет")).toBeInTheDocument();
  });

  it("общий поиск находит и статьи Платформы, и статьи компании; у статьи компании — пометка", async () => {
    signInAs("manager@demo.example");
    renderApp("/help/articles");
    const search = await screen.findByRole("textbox", { name: "Поиск по статьям" });
    await screen.findByRole("link", { name: "Кто согласует договор" });

    fireEvent.change(search, { target: { value: "договор" } });
    const hit = await screen.findByRole("link", { name: "Кто согласует договор" });
    expect(hit.closest("li")).toHaveTextContent("Как у нас принято");

    fireEvent.change(search, { target: { value: "резолюция" } });
    expect(await screen.findByRole("link", { name: /Входящие письма/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Кто согласует договор" })).toBeNull();

    fireEvent.change(search, { target: { value: "шаблоны писем" } });
    expect(
      await screen.findByRole("link", { name: "Где лежат шаблоны писем" }),
    ).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "отпусков" } });
    expect(await screen.findByText(/статей нет/)).toBeInTheDocument();
  });

  it("окно «?»: раздел «Как у нас принято», поиск по статьям компании и открытие статьи в окне", async () => {
    signInAs("manager@demo.example");
    renderApp("/chats/contacts");
    const help = await openHelp();
    const section = await within(help).findByRole("region", { name: "Как у нас принято" });
    expect(within(section).getByRole("button", { name: "Кто согласует договор" })).toBeVisible();

    const search = within(help).getByRole("textbox", { name: "Поиск по статьям" });
    fireEvent.change(search, { target: { value: "шаблоны" } });
    const found = await within(help).findByRole("button", { name: "Где лежат шаблоны писем" });
    expect(found.closest("li")).toHaveTextContent("Как у нас принято");
    fireEvent.click(found);
    expect(
      await within(help).findByRole("heading", { name: "Где лежат шаблоны писем" }),
    ).toBeInTheDocument();
    expect(
      within(help).getByRole("link", { name: "Открыть на странице «Помощь»" }),
    ).toHaveAttribute("href", "/help/articles/company-2");
  });

  it("нет опубликованных статей — раздел не мешает окну, а страница честно говорит «пока нет»", async () => {
    clearCompanyArticlesMock();
    signInAs("manager@demo.example");
    renderApp("/chats/contacts");
    const help = await openHelp();
    expect(within(help).queryByRole("region", { name: "Как у нас принято" })).toBeNull();
    cleanup();
    renderApp("/help/articles");
    const section = await screen.findByRole("region", { name: "Как у нас принято" });
    expect(await within(section).findByText("Статей компании пока нет.")).toBeInTheDocument();
  });

  it("CRM не отдала статьи компании — продуктовые статьи работают, в разделе сказано об этом", async () => {
    server.use(
      http.get("*/help/company-articles", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "CRM не отвечает", source: "crm" },
          { status: 503 },
        ),
      ),
    );
    signInAs("manager@demo.example");
    renderApp("/help/articles");
    const product = await screen.findByRole("region", { name: "Статьи Платформы" });
    expect(within(product).getByRole("link", { name: /Мои задачи/ })).toBeVisible();
    const section = screen.getByRole("region", { name: "Как у нас принято" });
    expect(
      await within(section).findByText(/Статьи компании сейчас недоступны/, undefined, {
        timeout: 15_000,
      }),
    ).toBeInTheDocument();
  }, 20_000);

  it("статья на другом языке, чем интерфейс, помечена своим языком", async () => {
    const state = readCompanyArticles();
    const first = state.articles[0];
    if (first) first.language = "uz";
    writeCompanyArticles(state);
    signInAs("manager@demo.example");
    renderApp("/help/articles/company-1");
    expect(await screen.findByText(/Статья написана на языке: Узбекский/)).toBeInTheDocument();
    cleanup();
    updateSession({ language: "en" });
    renderApp("/help/articles");
    expect(await screen.findByRole("region", { name: "How we do it" })).toBeInTheDocument();
  });

  it("опасный текст статьи компании в Помощи остаётся текстом", async () => {
    const state = readCompanyArticles();
    state.articles.push({
      id: 50,
      title: "Тест разметки",
      body: '<script>window.__xss=1</script> <img src=x onerror="window.__xss=2">\n\n[клик](javascript:alert(1))',
      language: "ru",
      status: "published",
      createdBy: "Админ",
      updatedBy: "Админ",
      createdAt: "2026-10-28T08:00:00.000Z",
      updatedAt: "2026-10-28T08:00:00.000Z",
      publishedAt: "2026-10-28T08:00:00.000Z",
    });
    writeCompanyArticles(state);
    signInAs("manager@demo.example");
    renderApp("/help/articles/company-50");
    const article = await screen.findByRole("article");
    expect(article.querySelector("script, img, a, iframe")).toBeNull();
    expect(within(article).getByText(/<script>window.__xss=1<\/script>/)).toBeInTheDocument();
    expect(within(article).getByText(/\[клик\]\(javascript:alert\(1\)\)/)).toBeInTheDocument();
    await waitFor(() => {
      expect((window as unknown as { __xss?: number }).__xss).toBeUndefined();
    });
  });
});

describe("слаг статьи компании", () => {
  it("company-<число> — статья компании; справка к экрану company-articles под него не подходит", () => {
    expect(COMPANY_PREFIX).toBe("company-");
    expect(companySlug(7)).toBe("company-7");
    expect(isCompanySlug("company-7")).toBe(true);
    expect(isCompanySlug("company-articles")).toBe(false);
    expect(isCompanySlug("queue")).toBe(false);
  });

  it("статья компании в виде статьи помощи: без разделов каталога, с языком и временем", () => {
    expect(
      toHelpArticle(
        {
          id: 4,
          title: "Т",
          body: "Текст",
          language: "en",
          status: "published",
          created_at: "2026-10-28T00:00:00Z",
          updated_at: "2026-10-28T01:00:00Z",
        },
        2,
      ),
    ).toEqual({
      slug: "company-4",
      title: "Т",
      sections: [],
      order: 2,
      body: "Текст",
      source: "company",
      language: "en",
      updatedAt: "2026-10-28T01:00:00Z",
    });
  });
});
