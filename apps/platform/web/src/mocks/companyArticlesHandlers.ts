import { HttpResponse, http } from "msw";

import type {
  CompanyArticle,
  CompanyArticleCreate,
  CompanyArticleLanguage,
  CompanyArticleUpdate,
} from "../shared/api/generated/model";
import { failure, guard } from "./adminUsers";
import { buildMe, readSession } from "./mockSession";
import {
  type StoredArticle,
  readCompanyArticles,
  writeCompanyArticles,
} from "./companyArticlesStore";

/**
 * Моки W18A-P5 (BFF, статьи компании): правила как у CRM — заголовок 1–200 символов, текст 1–20000, язык из списка;
 * новая статья — черновик, опубликовать и снять — отдельные действия; список для Помощи — только опубликованные;
 * все статьи — раздел `admin` от чтения, запись — `admin` полный.
 */
const TITLE_MAX = 200;
const BODY_MAX = 20000;
const LANGUAGES: readonly CompanyArticleLanguage[] = ["ru", "uz", "en"];

function row(a: StoredArticle): CompanyArticle {
  return {
    id: a.id,
    title: a.title,
    body: a.body,
    language: a.language,
    status: a.status,
    created_by_name: a.createdBy,
    updated_by_name: a.updatedBy,
    created_at: a.createdAt,
    updated_at: a.updatedAt,
    ...(a.publishedAt ? { published_at: a.publishedAt } : {}),
  };
}

const invalid = (field: string, reason: string, message: string) =>
  failure(422, "VALIDATION_FAILED", message, "crm", { fields: [field], reason });

function checkTitle(raw: string) {
  const title = raw.split(/\s+/).filter(Boolean).join(" ");
  if (!title) return { error: invalid("title", "article_title_empty", "Напишите заголовок.") };
  if (title.length > TITLE_MAX) {
    return {
      error: invalid(
        "title",
        "article_title_too_long",
        "Заголовок длиннее 200 символов: сократите его.",
      ),
    };
  }
  return { value: title };
}

function checkBody(raw: string) {
  const body = raw.trim();
  if (!body) return { error: invalid("body", "article_body_empty", "Напишите текст статьи.") };
  if (body.length > BODY_MAX) {
    return {
      error: invalid(
        "body",
        "article_body_too_long",
        "Текст длиннее 20000 символов: сократите его.",
      ),
    };
  }
  return { value: body };
}

const notFound = () => failure(404, "NOT_FOUND", "Не найдено.", "crm");
const myName = () => {
  const session = readSession();
  return (session ? buildMe(session)?.name : undefined) ?? "Администратор";
};
const byUpdated = (a: StoredArticle, b: StoredArticle) =>
  b.updatedAt.localeCompare(a.updatedAt) || b.id - a.id;

function find(id: unknown) {
  const state = readCompanyArticles();
  const article = state.articles.find((a) => a.id === Number(id));
  return { state, article };
}

export const companyArticlesHandlers = [
  http.get("*/help/company-articles", () => {
    if (!readSession()) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    const items = readCompanyArticles()
      .articles.filter((a) => a.status === "published")
      .sort((a, b) => (b.publishedAt ?? "").localeCompare(a.publishedAt ?? "") || b.id - a.id);
    return HttpResponse.json({ items: items.map(row) });
  }),

  http.get("*/admin/company-articles", () => {
    const denied = guard("read");
    if (denied) return denied;
    return HttpResponse.json({ items: readCompanyArticles().articles.sort(byUpdated).map(row) });
  }),

  http.post("*/admin/company-articles", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const input = (await request.json()) as CompanyArticleCreate;
    const title = checkTitle(input.title);
    if (title.error) return title.error;
    const body = checkBody(input.body);
    if (body.error) return body.error;
    const language = input.language ?? "ru";
    if (!LANGUAGES.includes(language)) {
      return invalid("language", "article_language_unknown", "Выберите язык из списка.");
    }
    const state = readCompanyArticles();
    const now = new Date().toISOString();
    const article: StoredArticle = {
      id: state.next++,
      title: title.value,
      body: body.value,
      language,
      status: "draft",
      createdBy: myName(),
      updatedBy: myName(),
      createdAt: now,
      updatedAt: now,
    };
    state.articles.push(article);
    writeCompanyArticles(state);
    return HttpResponse.json(row(article), { status: 201 });
  }),

  http.patch("*/admin/company-articles/:id", async ({ params, request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const input = (await request.json()) as CompanyArticleUpdate;
    const { state, article } = find(params["id"]);
    if (!article) return notFound();
    if (input.title !== undefined) {
      const title = checkTitle(input.title);
      if (title.error) return title.error;
      article.title = title.value;
    }
    if (input.body !== undefined) {
      const body = checkBody(input.body);
      if (body.error) return body.error;
      article.body = body.value;
    }
    if (input.language !== undefined) {
      if (!LANGUAGES.includes(input.language)) {
        return invalid("language", "article_language_unknown", "Выберите язык из списка.");
      }
      article.language = input.language;
    }
    article.updatedAt = new Date().toISOString();
    article.updatedBy = myName();
    writeCompanyArticles(state);
    return HttpResponse.json(row(article));
  }),

  http.post("*/admin/company-articles/:id/publish", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const { state, article } = find(params["id"]);
    if (!article) return notFound();
    if (article.status !== "published") {
      const now = new Date().toISOString();
      article.status = "published";
      article.publishedAt = now;
      article.updatedAt = now;
      article.updatedBy = myName();
      writeCompanyArticles(state);
    }
    return HttpResponse.json(row(article));
  }),

  http.post("*/admin/company-articles/:id/unpublish", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const { state, article } = find(params["id"]);
    if (!article) return notFound();
    if (article.status !== "draft") {
      article.status = "draft";
      delete article.publishedAt;
      article.updatedAt = new Date().toISOString();
      article.updatedBy = myName();
      writeCompanyArticles(state);
    }
    return HttpResponse.json(row(article));
  }),

  http.delete("*/admin/company-articles/:id", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const { state, article } = find(params["id"]);
    if (!article) return notFound();
    state.articles = state.articles.filter((a) => a.id !== article.id);
    writeCompanyArticles(state);
    return new HttpResponse(null, { status: 204 });
  }),
];
