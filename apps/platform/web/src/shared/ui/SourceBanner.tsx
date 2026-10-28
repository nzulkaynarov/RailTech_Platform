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
  /**
   * Свои тексты вместо «ERP не отвечает, данные неполные» (например, для очереди — с названиями разделов): по одному
   * источнику — `crm`, `erp`, `eds`; CRM и ERP вместе — `both`; любые другие сочетания (с EDS) — `multi`.
   */
  messages?: Partial<Record<"crm" | "erp" | "eds" | "both" | "multi", string>>;
}

/**
 * Плашка частичных данных (docs/architecture/platform-frontend.md §5, контракт BFF «Частичные данные»): «ERP не отвечает, данные неполные».
 * `role="status"` — вежливое объявление, не прерывающее чтение; если все источники в порядке, плашки нет.
 */
/** Какой текст плашки: один источник — его ключ, CRM и ERP — `both`, всё остальное (с EDS) — `multi`. */
export function bannerKind(
  crm: boolean,
  erp: boolean,
  eds: boolean,
): "crm" | "erp" | "eds" | "both" | "multi" {
  const down = [crm, erp, eds].filter(Boolean).length;
  if (down > 1) return crm && erp && !eds ? "both" : "multi";
  return crm ? "crm" : erp ? "erp" : "eds";
}

export function SourceBanner({ sources, onRetry, messages }: SourceBannerProps) {
  const { t } = useTranslation("ui");
  if (!sources) return null;
  const crm = sources.crm === "unavailable";
  const erp = sources.erp === "unavailable";
  const eds = sources.eds === "unavailable";
  if (!crm && !erp && !eds) return null;
  const kind = bannerKind(crm, erp, eds);
  return (
    <div className="pf-source" role="status">
      <span className="pf-source-icon">
        <WarningIcon />
      </span>
      <span className="pf-source-text">{messages?.[kind] ?? t(`source.${kind}`)}</span>
      {onRetry ? (
        <Button size="small" onClick={onRetry}>
          {t("source.retry")}
        </Button>
      ) : null}
    </div>
  );
}
