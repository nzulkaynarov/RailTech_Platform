import { Button } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { WriteToAdminModal } from "../tickets/WriteToAdminModal";
import { type HelpArticle } from "./articles";

import "./help.css";

/**
 * Под статьёй (W-REL): «Статья помогла? Да / Нет» и «Здесь устарело». «Устарело» и «Нет → Написать администратору»
 * открывают обращение администратору (механизм W15-H7) с темой «Другое», названием статьи и ссылкой на неё — сотрудник
 * дописывает, что не так, и отправляет. «Да» ничего не отправляет: это ответ сотруднику, а не сбор статистики.
 */
export function ArticleFeedback({ article }: { article: HelpArticle }) {
  const { t } = useTranslation("help");
  const questionId = useId();
  const [answer, setAnswer] = useState<"yes" | "no" | null>(null);
  const [writing, setWriting] = useState<"outdated" | "missing" | null>(null);
  const link = `/help/articles/${article.slug}`;

  return (
    <div className="pf-help-feedback" role="group" aria-label={t("feedback.label")}>
      {answer === null ? (
        <>
          <span id={questionId}>{t("feedback.question")}</span>
          <Button
            size="small"
            aria-describedby={questionId}
            onClick={() => {
              setAnswer("yes");
            }}
          >
            {t("feedback.yes")}
          </Button>
          <Button
            size="small"
            aria-describedby={questionId}
            onClick={() => {
              setAnswer("no");
            }}
          >
            {t("feedback.no")}
          </Button>
        </>
      ) : null}
      <div aria-live="polite" style={{ display: "contents" }}>
        {answer === "yes" ? <p style={{ margin: 0 }}>{t("feedback.thanks")}</p> : null}
        {answer === "no" ? (
          <>
            <p style={{ margin: 0 }}>{t("feedback.sorry")}</p>
            <Button
              size="small"
              onClick={() => {
                setWriting("missing");
              }}
            >
              {t("feedback.write")}
            </Button>
          </>
        ) : null}
      </div>
      <Button
        size="small"
        type="link"
        style={{ marginLeft: "auto", paddingInline: 0 }}
        onClick={() => {
          setWriting("outdated");
        }}
      >
        {t("feedback.outdated")}
      </Button>
      {writing ? (
        <WriteToAdminModal
          open
          defaultSubject="other"
          defaultBody={t(
            writing === "outdated" ? "feedback.outdatedBody" : "feedback.missingBody",
            {
              title: article.title,
              link,
            },
          )}
          onClose={() => {
            setWriting(null);
          }}
        />
      ) : null}
    </div>
  );
}
