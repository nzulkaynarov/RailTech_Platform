import { Button, Drawer, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useViewport } from "../../app/shell/useViewport";
import { WriteToAdminModal } from "../tickets/WriteToAdminModal";
import { ArticleView } from "./ArticleView";
import { StatusTag } from "../../shared/ui/StatusTag";
import { HELP_ARTICLES, articleForSection, findArticle, searchArticles } from "./articles";
import { useWhatsNew } from "./whatsNew";

import "./help.css";

export interface HelpDrawerProps {
  open: boolean;
  onClose: () => void;
  /** Ключ раздела `<модуль>.<раздел>` (`me` — профиль); по нему выбирается статья «К этому разделу» */
  sectionKey?: string;
}

/**
 * Окно «Помощь» (W15-H7, UX-оценка P1-2): справа, не уводит с экрана. Статья текущего раздела, поиск по статьям,
 * «Все статьи» и «Написать администратору». Фокус внутри окна, Escape закрывает и возвращает фокус на «?» — это
 * делает Drawer antd; ссылки закрывают окно, потому что ведут на другую страницу.
 */
export function HelpDrawer({ open, onClose, sectionKey }: HelpDrawerProps) {
  const { t } = useTranslation("help");
  const { mobile } = useViewport();
  const searchId = useId();
  const [query, setQuery] = useState("");
  const [slug, setSlug] = useState<string | null>(null);
  const [writing, setWriting] = useState(false);
  const { fresh } = useWhatsNew();

  // Каждое открытие и смена раздела — статья текущего раздела, а не прошлый поиск (сброс при отрисовке, без эффекта).
  const [seen, setSeen] = useState({ open, sectionKey });
  if (seen.open !== open || seen.sectionKey !== sectionKey) {
    setSeen({ open, sectionKey });
    if (open) {
      setQuery("");
      setSlug(null);
    }
  }

  const forSection = articleForSection(sectionKey);
  const chosen = slug ? findArticle(slug) : undefined;
  const article = chosen ?? (query.trim() === "" ? forSection : undefined);
  const hits = query.trim() === "" ? [] : searchArticles(query);

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        title={t("drawer.title")}
        width={mobile ? "100vw" : 400}
        placement="right"
        destroyOnHidden
        footer={
          <div className="pf-help-actions">
            <Link to="/help/articles" onClick={onClose} className="pf-help-link pf-focusable">
              {t("drawer.all")}
            </Link>
            <Link to="/help/requests" onClick={onClose} className="pf-help-link pf-focusable">
              {t("drawer.myRequests")}
            </Link>
            <Button
              type="primary"
              style={{ marginLeft: "auto" }}
              onClick={() => {
                setWriting(true);
              }}
            >
              {t("drawer.write")}
            </Button>
          </div>
        }
      >
        <div className="pf-help-block">
          {fresh ? (
            <p style={{ margin: 0, display: "flex", gap: 8, alignItems: "center" }}>
              <StatusTag tone="red">{t("whatsNew.fresh")}</StatusTag>
              <Link to="/help/news" onClick={onClose} className="pf-help-link pf-focusable">
                {t("whatsNew.open")}
              </Link>
            </p>
          ) : null}
          <div>
            <label
              htmlFor={searchId}
              className="pf-hint"
              style={{ display: "block", marginBottom: 4 }}
            >
              {t("drawer.searchLabel")}
            </label>
            <Input
              id={searchId}
              allowClear
              value={query}
              placeholder={t("drawer.searchPlaceholder")}
              onChange={(event) => {
                setQuery(event.target.value);
                setSlug(null);
              }}
            />
          </div>
          <div aria-live="polite">
            {query.trim() !== "" && !chosen ? (
              hits.length > 0 ? (
                <>
                  <p className="pf-hint" style={{ margin: "0 0 4px" }}>
                    {t("drawer.found", { count: hits.length })}
                  </p>
                  <ul className="pf-help-list" aria-label={t("drawer.articlesLabel")}>
                    {hits.map((hit) => (
                      <li key={hit.slug}>
                        <button
                          type="button"
                          className="pf-help-link pf-focusable"
                          style={{
                            border: 0,
                            background: "none",
                            padding: 0,
                            textAlign: "left",
                            cursor: "pointer",
                            font: "inherit",
                            fontWeight: 500,
                          }}
                          onClick={() => {
                            setSlug(hit.slug);
                          }}
                        >
                          {hit.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p style={{ margin: 0 }}>{t("drawer.noResults", { query: query.trim() })}</p>
              )
            ) : null}
          </div>
          {article ? (
            <>
              <ArticleView article={article} />
              <Link
                to={`/help/articles/${article.slug}`}
                onClick={onClose}
                className="pf-help-link pf-focusable"
              >
                {t("drawer.readFull")}
              </Link>
            </>
          ) : query.trim() === "" ? (
            <div className="pf-help-block">
              <p style={{ margin: 0 }}>{t("drawer.noArticle")}</p>
              <ul className="pf-help-list" aria-label={t("drawer.articlesLabel")}>
                {HELP_ARTICLES.slice(0, 5).map((item) => (
                  <li key={item.slug}>
                    <button
                      type="button"
                      className="pf-help-link pf-focusable"
                      style={{
                        border: 0,
                        background: "none",
                        padding: 0,
                        textAlign: "left",
                        cursor: "pointer",
                        font: "inherit",
                        fontWeight: 500,
                      }}
                      onClick={() => {
                        setSlug(item.slug);
                      }}
                    >
                      {item.title}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </Drawer>
      {writing ? (
        <WriteToAdminModal
          open
          onClose={() => {
            setWriting(false);
          }}
        />
      ) : null}
    </>
  );
}
