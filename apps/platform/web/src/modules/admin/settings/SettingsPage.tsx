import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Link } from "react-router";

import { articleForSection } from "../../../features/help/articles";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { LockIcon } from "../../../shared/ui/icons";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { useSettingsEditable } from "./useSettingsEditable";

import "./settings.css";

/**
 * Рамка страницы Настроек (SET-IA): заголовок — название из реестра (`modules:admin.sections.<key>`, то же, что в меню и в
 * поиске), подзаголовок — одна строка или его нет (CONVENTIONS §2 п. 17); директору — плашка «Только просмотр».
 */
export function SettingsPage({
  sectionKey,
  subtitle,
  extra,
  editable: given,
  children,
}: {
  sectionKey: string;
  /** Правит ли сотрудник то, что открыто (справочники «Расчёта» правит и директор); нет — по разделу Настроек. */
  editable?: boolean;
  subtitle?: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
}) {
  const { t } = useTranslation("modules");
  const bySection = useSettingsEditable(sectionKey);
  const editable = given ?? bySection;
  const title = t(`admin.sections.${sectionKey}`);
  useDocumentTitle(title);
  // Больше одной строки — в справку (ресёрч §4.2 п. 2): «Подробнее» ведёт в статью Помощи этой страницы.
  const article = articleForSection(`admin.${sectionKey}`);
  const more = article ? (
    <Link
      className="pf-focusable pf-set-more"
      to={`/help/articles/${article.slug}`}
      aria-label={t("admin.home.moreAria", { title })}
    >
      {t("admin.home.more")}
    </Link>
  ) : null;
  return (
    <div className="pf-set-page">
      <PageHeader
        title={title}
        subtitle={subtitle}
        extra={
          <div className="pf-set-head-extra">
            {editable ? (
              extra
            ) : (
              <StatusTag tone="default">
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <LockIcon size={12} />
                  {t("admin.home.viewOnly")}
                </span>
              </StatusTag>
            )}
            {more}
          </div>
        }
      />
      {children}
    </div>
  );
}
