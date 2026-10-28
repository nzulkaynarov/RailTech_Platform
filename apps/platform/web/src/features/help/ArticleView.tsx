import { useTranslation } from "react-i18next";

import { type HelpArticle } from "./articles";
import { Markdown } from "./Markdown";

import "./help.css";

/** Статья помощи: заголовок и текст. Статьи пока на русском — на другом языке интерфейса честно сказано об этом. */
export function ArticleView({
  article,
  headingLevel = 2,
}: {
  article: HelpArticle;
  /** Уровень заголовка статьи: на странице под `h1` — 2, в окне помощи — 2 */
  headingLevel?: 2 | 3;
}) {
  const { t, i18n } = useTranslation("help");
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <article aria-labelledby={`article-${article.slug}`}>
      <Heading
        id={`article-${article.slug}`}
        style={{ margin: "0 0 8px", fontSize: 16, lineHeight: "24px", fontWeight: 600 }}
      >
        {article.title}
      </Heading>
      {i18n.language === "ru" ? null : (
        <p className="pf-hint" style={{ margin: "0 0 8px" }}>
          {t("drawer.onlyRussian")}
        </p>
      )}
      <Markdown source={article.body} headingLevel={(headingLevel + 1) as 3 | 4} />
    </article>
  );
}
