import { Button, Card } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { useDocumentTitle } from "../../shared/lib/useDocumentTitle";
import { EmptyState } from "../../shared/ui/EmptyState";
import { PageHeader } from "../../shared/ui/PageHeader";
import { MyRequests } from "../tickets/MyRequests";
import { WriteToAdminModal } from "../tickets/WriteToAdminModal";
import { ArticleList } from "./ArticleList";
import { ArticleView } from "./ArticleView";
import { findArticle } from "./articles";
import { Glossary, Hotkeys, News, PathGuide, StartGuide } from "./HelpSections";

import "./help.css";

const TABS = ["start", "path", "glossary", "articles", "keys", "news", "requests"] as const;
type Tab = (typeof TABS)[number];

const isTab = (value: string | undefined): value is Tab => TABS.some((tab) => tab === value);

/**
 * Раздел `/help` (W15-H7, UX-оценка P1-2): «С чего начать» по ролям, путь заявки (7 шагов), словарь, статьи,
 * горячие клавиши, «Что нового» и «Мои обращения». Вкладка — часть адреса (`/help/glossary`, `/help/articles/<статья>`,
 * `/help/requests/ОБР-0012`), чтобы на неё можно было сослаться и вернуться кнопкой «Назад».
 */
export function HelpPage() {
  const { t } = useTranslation("help");
  const rest = (useParams()["*"] ?? "").split("/").filter(Boolean).map(decodeURIComponent);
  const head = rest[0];
  const tab: Tab = isTab(head) ? head : "start";
  const unknown = head !== undefined && !isTab(head);
  const [writing, setWriting] = useState(false);
  const title = t("page.title");
  useDocumentTitle(title);

  let content;
  if (unknown) {
    content = (
      <EmptyState
        title={t("page.notFoundTitle")}
        text={t("page.notFoundText")}
        action={
          <Link to="/help" className="pf-help-link pf-focusable">
            {t("page.title")}
          </Link>
        }
      />
    );
  } else if (tab === "start") content = <StartGuide />;
  else if (tab === "path") content = <PathGuide />;
  else if (tab === "glossary") content = <Glossary />;
  else if (tab === "keys") content = <Hotkeys />;
  else if (tab === "news") content = <News />;
  else if (tab === "requests") content = <MyRequests {...(rest[1] ? { number: rest[1] } : {})} />;
  else if (rest[1]) {
    const article = findArticle(rest[1]);
    content = article ? (
      <div className="pf-help-block">
        <Link to="/help/articles" className="pf-help-link pf-focusable">
          {t("page.back")}
        </Link>
        <ArticleView article={article} />
      </div>
    ) : (
      <EmptyState
        title={t("page.notFoundTitle")}
        text={t("page.notFoundText")}
        action={
          <Link to="/help/articles" className="pf-help-link pf-focusable">
            {t("page.back")}
          </Link>
        }
      />
    );
  } else content = <ArticleList />;

  return (
    <>
      <PageHeader
        title={title}
        subtitle={t("page.subtitle")}
        extra={
          <Button
            type="primary"
            onClick={() => {
              setWriting(true);
            }}
          >
            {t("page.write")}
          </Button>
        }
      />
      <Card>
        <nav aria-label={t("page.tabsLabel")} className="pf-help-nav">
          <ul>
            {TABS.map((key) => (
              <li key={key}>
                <Link
                  to={key === "start" ? "/help" : `/help/${key}`}
                  aria-current={!unknown && key === tab ? "page" : undefined}
                  className="pf-help-navlink pf-focusable"
                >
                  {t(`page.tabs.${key}`)}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        {content}
      </Card>
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

export const Component = HelpPage;
