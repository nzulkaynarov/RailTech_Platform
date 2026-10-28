/**
 * Статьи помощи сотрудникам (W15-H7): файлы `docs/kb/help/*.md` (копия в `src/generated/help-articles` — `pnpm kb:sync`,
 * равенство проверяет `articles.test.ts`). Это не база знаний бота для клиентов: у статей свой каталог. Правит статьи тот,
 * у кого есть доступ к репозиторию (PR в `docs/kb/help`); из интерфейса админ их пока не редактирует — хвост в QUESTIONS.
 *
 * Статьи компании («Как у нас принято», W18A-P5) приходят из CRM через BFF — `companyArticles.ts`; поиск и просмотр
 * у тех и других общие.
 *
 * Формат: front matter (`title`, `sections` — ключи разделов `<модуль>.<раздел>` или `me`, `order`, `screens` — адреса экранов
 * `[/crm/leads, /crm/clients]`, по которым CI предупреждает, что экран поменяли, а статью нет; W-REL), затем текст в простом
 * markdown: `##`-заголовки, абзацы, списки `-` и `1.`, **жирный**, `код`.
 */
const files = import.meta.glob<string>("../../generated/help-articles/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
});

export interface HelpArticle {
  slug: string;
  title: string;
  /** Ключи разделов, к которым статья — «К этому разделу» (`dashboard.queue`, `me`) */
  sections: readonly string[];
  /** Адреса экранов, о которых статья (`/crm/leads`); пусто — статья не про один экран */
  screens: readonly string[];
  order: number;
  body: string;
  /** Откуда статья: без поля — продуктовая (`docs/kb/help`); `company` — статья компании из CRM (W18A-P5, B-079) */
  source?: "company";
  /** Язык статьи компании (`ru`, `uz`, `en`); у продуктовых статей поля нет — они русские */
  language?: string;
  /** Когда статья компании обновлена (ISO) */
  updatedAt?: string;
}

/** Список во front matter: `a, b` или `[a, b]`. */
export function listOf(value: string | undefined): string[] {
  return (value ?? "")
    .replace(/^\[|\]$/g, "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseArticle(slug: string, source: string): HelpArticle {
  const match = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(source);
  const head = match?.[1] ?? "";
  const body = (match?.[2] ?? source).trim();
  const meta = new Map<string, string>();
  for (const line of head.split("\n")) {
    const at = line.indexOf(":");
    if (at > 0) meta.set(line.slice(0, at).trim(), line.slice(at + 1).trim());
  }
  return {
    slug,
    title: meta.get("title") ?? slug,
    sections: listOf(meta.get("sections")),
    screens: listOf(meta.get("screens")),
    order: Number(meta.get("order") ?? 1000) || 1000,
    body,
  };
}

function load(): HelpArticle[] {
  return Object.entries(files)
    .map(([path, source]) =>
      parseArticle(path.split("/").pop()?.replace(/\.md$/, "") ?? path, source),
    )
    .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title, "ru"));
}

export const HELP_ARTICLES: readonly HelpArticle[] = load();

export function findArticle(slug: string): HelpArticle | undefined {
  return HELP_ARTICLES.find((article) => article.slug === slug);
}

/** Статья к разделу: первая, чей `sections` содержит ключ (`crm.leads`, `me`); нет — `undefined`. */
export function articleForSection(key: string | undefined): HelpArticle | undefined {
  return key ? HELP_ARTICLES.find((article) => article.sections.includes(key)) : undefined;
}

const normalize = (text: string) => text.toLocaleLowerCase("ru").replaceAll("ё", "е");

/**
 * Поиск по статьям: каждое слово запроса должно встретиться в заголовке или тексте (начало слова или его часть, без
 * регистра и «ё»). Совпадение в заголовке выше совпадения в тексте. Слова короче двух букв игнорируются.
 */
export function searchArticles(query: string, articles: readonly HelpArticle[] = HELP_ARTICLES) {
  const words = normalize(query)
    .split(/[\s,.;:!?()«»"]+/)
    .filter((word) => word.length >= 2);
  if (words.length === 0) return [];
  return articles
    .map((article) => {
      const title = normalize(article.title);
      const body = normalize(article.body);
      let score = 0;
      for (const word of words) {
        if (title.includes(word)) score += 3;
        else if (body.includes(word)) score += 1;
        else return { article, score: 0 };
      }
      return { article, score };
    })
    .filter((hit) => hit.score > 0)
    .sort((a, b) => b.score - a.score || a.article.order - b.article.order)
    .map((hit) => hit.article);
}
