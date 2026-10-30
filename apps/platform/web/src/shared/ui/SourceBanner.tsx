import { Button } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Sources } from "../api/generated/model";
import { WarningIcon } from "./icons";
import { bannerKind } from "./bannerKind";
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

/** Сколько новое состояние источников должно продержаться, чтобы плашка появилась или исчезла (UX-1c, S10). */
export const SOURCE_SETTLE_MS = 3_000;

type Kind = ReturnType<typeof bannerKind> | "none";

function kindOf(sources: Sources | undefined): Kind | undefined {
  if (!sources) return undefined;
  const crm = sources.crm === "unavailable";
  const erp = sources.erp === "unavailable";
  const eds = sources.eds === "unavailable";
  return crm || erp || eds ? bannerKind(crm, erp, eds) : "none";
}

/**
 * Плашка не мигает (UX-1c, аудит 2026-10-30, S10): первое известное состояние — сразу (вместе с данными экрана), а смена
 * (источник ответил или снова упал при опросе) — только если продержалась `SOURCE_SETTLE_MS`. Пока ответа нет
 * (`undefined`, перезапрос) — прежнее состояние.
 */
function useSettledKind(next: Kind | undefined): Kind | undefined {
  const [settled, setSettled] = useState<Kind | undefined>(next);
  if (settled === undefined && next !== undefined) setSettled(next);
  useEffect(() => {
    if (next === undefined || settled === undefined || next === settled) return;
    const timer = window.setTimeout(() => {
      setSettled(next);
    }, SOURCE_SETTLE_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [next, settled]);
  return settled;
}

/**
 * Плашка частичных данных (docs/architecture/platform-frontend.md §5, контракт BFF «Частичные данные»): «ERP не отвечает, данные неполные».
 * `role="status"` — вежливое объявление, не прерывающее чтение; если все источники в порядке, плашки нет. Появляется и
 * исчезает с задержкой `SOURCE_SETTLE_MS`, кроме первого состояния (`useSettledKind`).
 */
export function SourceBanner({ sources, onRetry, messages }: SourceBannerProps) {
  const { t } = useTranslation("ui");
  const kind = useSettledKind(kindOf(sources));
  if (kind === undefined || kind === "none") return null;
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
