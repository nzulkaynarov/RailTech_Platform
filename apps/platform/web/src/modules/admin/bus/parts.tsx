import { Button, Select } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { BusSources } from "../../../shared/api/generated/model";
import { WarningIcon } from "../../../shared/ui/icons";
import { domainName, troubledSources } from "./format";

import "./bus.css";

/**
 * Фильтр-список — antd `Select` с подписью `label for={id}` (UX-2a: системных `select` в Платформе нет); поиск — когда
 * вариантов больше семи; вид и высота — как у остальных полей фильтра.
 */
export function FilterSelect<T extends string>({
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
    <Select<T>
      id={id}
      className="pf-bus-select"
      value={value}
      showSearch={options.length > 7}
      optionFilterProp="label"
      popupMatchSelectWidth={false}
      options={options.map((option) => ({ value: option.value, label: option.label }))}
      onChange={(next) => {
        onChange(next);
      }}
    />
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
