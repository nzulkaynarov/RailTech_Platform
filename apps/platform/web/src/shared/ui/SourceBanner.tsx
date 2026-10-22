import { Button } from "antd";
import { useTranslation } from "react-i18next";

import type { Sources } from "../api/generated/model";
import { WarningIcon } from "./icons";
import "./ui.css";

export interface SourceBannerProps {
  /** Флаг `sources` из ответа BFF; `not_applicable` не считается сбоем (у сотрудника нет доступа к бэкенду) */
  sources: Sources | undefined;
  /** Повторить запрос; без обработчика кнопки нет */
  onRetry?: () => void;
}

/**
 * Плашка частичных данных (03-frontend.md §5, контракт BFF «Частичные данные»): «ERP не отвечает, данные неполные».
 * `role="status"` — вежливое объявление, не прерывающее чтение; если оба бэкенда в порядке, плашки нет.
 */
export function SourceBanner({ sources, onRetry }: SourceBannerProps) {
  const { t } = useTranslation("ui");
  if (!sources) return null;
  const crm = sources.crm === "unavailable";
  const erp = sources.erp === "unavailable";
  if (!crm && !erp) return null;
  return (
    <div className="pf-source" role="status">
      <span className="pf-source-icon">
        <WarningIcon />
      </span>
      <span className="pf-source-text">
        {t(crm && erp ? "source.both" : erp ? "source.erp" : "source.crm")}
      </span>
      {onRetry ? (
        <Button size="small" onClick={onRetry}>
          {t("source.retry")}
        </Button>
      ) : null}
    </div>
  );
}
