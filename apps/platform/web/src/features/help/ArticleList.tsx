import { Input, Skeleton } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { type HelpArticle, searchArticles } from "./articles";
import { useHelpArticles } from "./companyArticles";

import "./help.css";

function Links({ items, label }: { items: readonly HelpArticle[]; label: string }) {
  return (
    <ul className="pf-help-list" aria-label={label}>
      {items.map((article) => (
        <li key={article.slug}>
          <Link to={`/help/articles/${article.slug}`} className="pf-help-link pf-focusable">
            {article.title}
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * «Статьи»: список с общим поиском. Две части: статьи Платформы и «Как у нас принято» — статьи компании, которые пишет
 * администратор (W18A-P5). Поиск идёт по обеим. Название — ссылка на статью `/help/articles/<slug>`.
 */
export function ArticleList() {
  const { t } = useTranslation(["help", "articles"]);
  const searchId = useId();
  const [query, setQuery] = useState("");
  const { product, company, all, pending, failed } = useHelpArticles();
  const searching = query.trim() !== "";
  const hits = searching ? searchArticles(query, all) : [];
  return (
    <div className="pf-help-block">
      <p style={{ margin: 0 }}>{t("articles.intro")}</p>
      <div style={{ maxWidth: 420 }}>
        <label htmlFor={searchId} className="pf-hint" style={{ display: "block", marginBottom: 4 }}>
          {t("drawer.searchLabel")}
        </label>
        <Input
          id={searchId}
          allowClear
          value={query}
          placeholder={t("drawer.searchPlaceholder")}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
      </div>
      <div aria-live="polite">
        {searching ? (
          hits.length === 0 ? (
            <p style={{ margin: 0 }}>{t("drawer.noResults", { query: query.trim() })}</p>
          ) : (
            <>
              <p className="pf-hint" style={{ margin: "0 0 4px" }}>
                {t("drawer.found", { count: hits.length })}
              </p>
              <ul className="pf-help-list" aria-label={t("page.tabs.articles")}>
                {hits.map((article) => (
                  <li key={article.slug}>
                    <Link
                      to={`/help/articles/${article.slug}`}
                      className="pf-help-link pf-focusable"
                    >
                      {article.title}
                    </Link>
                    {article.source === "company" ? (
                      <span className="pf-hint"> · {t("articles:help.kindCompany")}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </>
          )
        ) : (
          <div className="pf-help-block" style={{ gap: 24 }}>
            <section aria-labelledby={`${searchId}-product`} className="pf-help-block">
              <h2
                id={`${searchId}-product`}
                style={{ margin: 0, fontSize: 16, lineHeight: "24px" }}
              >
                {t("articles:help.productSection")}
              </h2>
              {product.length === 0 ? (
                <p style={{ margin: 0 }}>{t("articles.empty")}</p>
              ) : (
                <Links items={product} label={t("articles:help.productSection")} />
              )}
            </section>
            <section aria-labelledby={`${searchId}-company`} className="pf-help-block">
              <h2
                id={`${searchId}-company`}
                style={{ margin: 0, fontSize: 16, lineHeight: "24px" }}
              >
                {t("articles:help.section")}
              </h2>
              <p className="pf-hint" style={{ margin: 0 }}>
                {t("articles:help.sectionHint")}
              </p>
              {pending ? (
                <Skeleton active paragraph={{ rows: 2 }} title={false} />
              ) : failed ? (
                <p style={{ margin: 0 }}>{t("articles:help.loadError")}</p>
              ) : company.length === 0 ? (
                <p style={{ margin: 0 }}>{t("articles:help.empty")}</p>
              ) : (
                <Links items={company} label={t("articles:help.section")} />
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
