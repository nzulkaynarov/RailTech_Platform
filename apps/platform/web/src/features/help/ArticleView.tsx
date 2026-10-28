import { useTranslation } from "react-i18next";

import { useFormat } from "../../shared/lib/useFormat";
import { ArticleFeedback } from "./ArticleFeedback";
import { type HelpArticle } from "./articles";
import { Markdown } from "./Markdown";

import "./help.css";

/**
 * Статья помощи: заголовок, текст и под ним «Помогла? Да / Нет» и «Здесь устарело» (W-REL). Продуктовые статьи пока на
 * русском — на другом языке интерфейса честно сказано об этом; статья компании помечена своим языком, если он не
 * совпал с языком интерфейса (W18A-P5).
 */
export function ArticleView({
  article,
  headingLevel = 2,
}: {
  article: HelpArticle;
  /** Уровень заголовка статьи: на странице под `h1` — 2, в окне помощи — 2 */
  headingLevel?: 2 | 3;
}) {
  const { t, i18n } = useTranslation(["help", "articles"]);
  const format = useFormat();
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const company = article.source === "company";
  const foreignLanguage =
    company && article.language !== undefined && article.language !== i18n.language;
  return (
    <article aria-labelledby={`article-${article.slug}`}>
      <Heading
        id={`article-${article.slug}`}
        style={{ margin: "0 0 8px", fontSize: 16, lineHeight: "24px", fontWeight: 600 }}
      >
        {article.title}
      </Heading>
      {company ? (
        <p className="pf-hint" style={{ margin: "0 0 8px" }}>
          {t("articles:help.kindCompany")}
          {article.updatedAt
            ? ` · ${t("articles:help.updated", { when: format.date(article.updatedAt) })}`
            : ""}
          {foreignLanguage
            ? ` · ${t("articles:help.otherLanguage", {
                language: t(`articles:admin.language.${article.language ?? "ru"}`),
              })}`
            : ""}
        </p>
      ) : i18n.language === "ru" ? null : (
        <p className="pf-hint" style={{ margin: "0 0 8px" }}>
          {t("drawer.onlyRussian")}
        </p>
      )}
      <Markdown source={article.body} headingLevel={(headingLevel + 1) as 3 | 4} />
      <ArticleFeedback article={article} />
    </article>
  );
}
