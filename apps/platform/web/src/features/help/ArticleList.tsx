import { Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { HELP_ARTICLES, searchArticles } from "./articles";

import "./help.css";

/** «Статьи»: список с поиском. Название — ссылка на статью `/help/articles/<slug>`. */
export function ArticleList() {
  const { t } = useTranslation("help");
  const searchId = useId();
  const [query, setQuery] = useState("");
  const items = query.trim() === "" ? HELP_ARTICLES : searchArticles(query);
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
        {items.length === 0 ? (
          <p style={{ margin: 0 }}>
            {query.trim() === ""
              ? t("articles.empty")
              : t("drawer.noResults", { query: query.trim() })}
          </p>
        ) : (
          <>
            {query.trim() === "" ? null : (
              <p className="pf-hint" style={{ margin: "0 0 4px" }}>
                {t("drawer.found", { count: items.length })}
              </p>
            )}
            <ul className="pf-help-list" aria-label={t("page.tabs.articles")}>
              {items.map((article) => (
                <li key={article.slug}>
                  <Link to={`/help/articles/${article.slug}`} className="pf-help-link pf-focusable">
                    {article.title}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
