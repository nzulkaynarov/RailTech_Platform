import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { MENU } from "../../app/rbac.generated";
import { HELP_ARTICLES, articleForSection, listOf, parseArticle, searchArticles } from "./articles";

const SOURCE = join(import.meta.dirname, "../../../../../../docs/kb/help");

describe("статьи помощи в сборке", () => {
  it("совпадают с docs/kb/help (источник правды); обновить — `pnpm kb:sync`", () => {
    const files = readdirSync(SOURCE).filter((name) => name.endsWith(".md"));
    expect(HELP_ARTICLES).toHaveLength(files.length);
    for (const name of files) {
      const slug = name.replace(/\.md$/, "");
      const expected = parseArticle(slug, readFileSync(join(SOURCE, name), "utf-8"));
      expect(
        HELP_ARTICLES.find((a) => a.slug === slug),
        slug,
      ).toEqual(expected);
    }
  });

  it("у каждой статьи есть заголовок, текст и порядок; заголовки и slug уникальны", () => {
    for (const article of HELP_ARTICLES) {
      expect(article.title, article.slug).not.toBe(article.slug);
      expect(article.body.length, article.slug).toBeGreaterThan(80);
    }
    expect(new Set(HELP_ARTICLES.map((a) => a.slug)).size).toBe(HELP_ARTICLES.length);
    expect(new Set(HELP_ARTICLES.map((a) => a.title)).size).toBe(HELP_ARTICLES.length);
  });

  it("статья к разделу: по ключу раздела; раздел без статьи — нет", () => {
    expect(articleForSection("eds.inbox")?.slug).toBe("inbox");
    expect(articleForSection("dashboard.queue")?.slug).toBe("queue");
    expect(articleForSection("admin.tickets")?.slug).toBe("admin-tickets");
    expect(articleForSection("me")?.slug).toBe("profile");
    expect(articleForSection("admin.bus")).toBeUndefined();
    expect(articleForSection(undefined)).toBeUndefined();
  });

  it("каждый раздел модулей, у которого есть статья, указан в статье верным ключом", () => {
    const keys = HELP_ARTICLES.flatMap((a) => a.sections);
    expect(keys.every((key) => key === "me" || /^[a-z]+\.[a-z]+$/.test(key))).toBe(true);
  });
});

describe("актуальность помощи (W-REL)", () => {
  // Новый пункт меню каталога без статьи — красный CI: добавьте статью в docs/kb/help (ключ раздела в `sections`).
  it("у каждого пункта меню каталога platform-rbac.yaml есть статья", () => {
    const covered = new Set(HELP_ARTICLES.flatMap((a) => a.sections));
    const missing = Object.entries(MENU).flatMap(([module, items]) =>
      Object.keys(items)
        .map((item) => `${module}.${item}`)
        .filter((key) => !covered.has(key)),
    );
    expect(missing).toEqual([]);
  });

  it("в каждой статье есть `screens` — адреса экранов (или пусто для общих статей)", () => {
    for (const name of readdirSync(SOURCE).filter((file) => file.endsWith(".md"))) {
      const head = readFileSync(join(SOURCE, name), "utf-8").split("\n---")[0] ?? "";
      expect(head, name).toMatch(/\nscreens: \[.*\]/);
    }
    for (const article of HELP_ARTICLES) {
      for (const screen of article.screens) expect(screen, article.slug).toMatch(/^\/[a-z/-]+$/);
    }
  });

  it("listOf: с квадратными скобками и без", () => {
    expect(listOf("[/a, /b]")).toEqual(["/a", "/b"]);
    expect(listOf("a.b, c.d")).toEqual(["a.b", "c.d"]);
    expect(listOf("[]")).toEqual([]);
    expect(listOf(undefined)).toEqual([]);
  });
});

describe("parseArticle", () => {
  it("front matter и текст; без front matter — весь текст", () => {
    const a = parseArticle(
      "x",
      "---\ntitle: Заголовок: с двоеточием\nsections: a.b, c.d\norder: 7\nscreens: [/a/b, /c]\n---\nТекст",
    );
    expect(a).toEqual({
      slug: "x",
      title: "Заголовок: с двоеточием",
      sections: ["a.b", "c.d"],
      screens: ["/a/b", "/c"],
      order: 7,
      body: "Текст",
    });
    expect(parseArticle("y", "просто текст")).toMatchObject({
      title: "y",
      sections: [],
      order: 1000,
    });
  });
});

describe("searchArticles", () => {
  it("находит по заголовку и тексту, без регистра и «ё»; заголовок выше", () => {
    expect(searchArticles("резолюция")[0]?.slug).toBe("inbox");
    expect(searchArticles("РЕЗОЛЮЦИЯ").map((a) => a.slug)).toContain("inbox");
    expect(searchArticles("все визы").length).toBeGreaterThan(0);
  });

  it("все слова запроса обязательны; короткие и пустые запросы ничего не находят", () => {
    expect(searchArticles("резолюция бухгалтер платёжка космос")).toEqual([]);
    expect(searchArticles("")).toEqual([]);
    expect(searchArticles("а")).toEqual([]);
  });

  it("находит статью про обращение к администратору", () => {
    const slugs = searchArticles("написать администратору").map((a) => a.slug);
    expect(slugs[0]).toBe("requests-to-admin");
  });
});
