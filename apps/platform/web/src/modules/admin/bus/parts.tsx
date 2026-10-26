import { Button } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { BusSources } from "../../../shared/api/generated/model";
import { WarningIcon } from "../../../shared/ui/icons";
import { domainName, troubledSources } from "./format";

import "./bus.css";

/**
 * Фильтр-список — родной `select` с подписью: доступен с клавиатуры и скринридеру без обходных путей, на телефоне
 * открывает системный список; вид — как у полей antd (32 px, рамка #d9d9d9, радиус 6).
 */
export function NativeSelect<T extends string>({
  id,
  value,
  onChange,
  options,
}: {
  id: string;
  value: T;
  onChange: (value: T) => void;
  options: readonly { value: T; label: string }[];
}) {
  return (
    <select
      id={id}
      className="pf-bus-select"
      value={value}
      onChange={(event) => {
        onChange(event.target.value as T);
      }}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

/** Таблица, которая прокручивается по горизонтали на узком экране: область доступна с клавиатуры (WCAG 2.1.1). */
export function ScrollRegion({ label, children }: { label: string; children: ReactNode }) {
  const { t } = useTranslation("bus");
  return (
    <div
      className="pf-bus-scroll"
      role="region"
      tabIndex={0}
      aria-label={t("tableScroll", { name: label })}
    >
      {children}
    </div>
  );
}

/**
 * Плашка частичных данных журнала: домен не ответил или отказал — словами и с кнопкой «Обновить»
 * (контракт BFF 0.9.0 `BusSources`; общая `SourceBanner` знает только CRM и ERP).
 */
export function BusSourcesNote({
  sources,
  onRetry,
}: {
  sources: BusSources | undefined;
  onRetry: () => void;
}) {
  const { t } = useTranslation("bus");
  const troubled = troubledSources(sources);
  if (troubled.length === 0) return null;
  return (
    <div className="pf-source" role="status">
      <span className="pf-source-icon">
        <WarningIcon />
      </span>
      <span className="pf-source-text">
        {troubled
          .map(({ domain, state }) => t(`sources.${state}`, { domain: domainName(t, domain) }))
          .join(" ")}
      </span>
      <Button size="small" onClick={onRetry}>
        {t("sources.retry")}
      </Button>
    </div>
  );
}
