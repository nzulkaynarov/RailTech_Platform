import { Button, Select, Switch } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import {
  AUDIT_ACTIONS,
  AUDIT_ENTITIES,
  actionLabel,
  entityLabel,
} from "../../../entities/audit/labels";
import { DateRangeField } from "../../../shared/ui/DateField";
import { type AuditFilterValues, hasFilters } from "./filters";

export interface AuditFiltersProps {
  value: AuditFilterValues;
  onChange: (next: AuditFilterValues) => void;
  /** Сотрудники для выбора автора */
  actors: readonly { id: string; name: string }[];
  /** Журнал сужен до одного объекта (`?entity_id=`) — например, до роли */
  entityId: string | null;
  onReset: () => void;
}

/** Фильтры журнала: автор, действие, объект, период и показ входов; каждый — с подписью над полем. */
export function AuditFilters({ value, onChange, actors, entityId, onReset }: AuditFiltersProps) {
  const { t } = useTranslation("audit");
  const base = useId();
  const set = (patch: Partial<AuditFilterValues>) => {
    onChange({ ...value, ...patch });
  };
  return (
    <form
      className="pf-audit-filters"
      role="search"
      aria-label={t("filters.label")}
      onSubmit={(event) => {
        event.preventDefault();
      }}
    >
      <div className="pf-audit-field">
        <label htmlFor={`${base}-actor`}>{t("filters.actor")}</label>
        <Select
          id={`${base}-actor`}
          showSearch
          allowClear
          optionFilterProp="label"
          placeholder={t("filters.allActors")}
          style={{ minWidth: 200 }}
          value={value.actor || undefined}
          options={actors.map((a) => ({ value: a.id, label: a.name }))}
          onChange={(v?: string) => {
            set({ actor: v ?? "" });
          }}
        />
      </div>
      <div className="pf-audit-field">
        <label htmlFor={`${base}-action`}>{t("filters.action")}</label>
        <Select
          id={`${base}-action`}
          showSearch
          allowClear
          optionFilterProp="label"
          placeholder={t("filters.allActions")}
          style={{ minWidth: 240 }}
          value={value.action || undefined}
          options={AUDIT_ACTIONS.map((code) => ({ value: code, label: actionLabel(t, code) }))}
          onChange={(v?: string) => {
            set({ action: v ?? "" });
          }}
        />
      </div>
      <div className="pf-audit-field">
        <label htmlFor={`${base}-entity`}>{t("filters.entity")}</label>
        <Select
          id={`${base}-entity`}
          allowClear
          placeholder={t("filters.allEntities")}
          style={{ minWidth: 200 }}
          value={value.entityType || undefined}
          options={AUDIT_ENTITIES.map((type) => ({ value: type, label: entityLabel(t, type) }))}
          onChange={(v?: string) => {
            set({ entityType: v ?? "" });
          }}
        />
      </div>
      <DateRangeField
        idFrom={`${base}-from`}
        idTo={`${base}-to`}
        labelFrom={t("filters.from")}
        labelTo={t("filters.to")}
        fieldClassName="pf-audit-field"
        style={{ width: 160 }}
        value={{ from: value.from, to: value.to }}
        onChange={(range) => {
          set(range);
        }}
      />
      <div className="pf-audit-logins">
        <Switch
          id={`${base}-logins`}
          checked={value.logins}
          onChange={(checked) => {
            set({ logins: checked });
          }}
        />
        <label htmlFor={`${base}-logins`}>{t("filters.logins")}</label>
      </div>
      {hasFilters(value, entityId) ? <Button onClick={onReset}>{t("filters.reset")}</Button> : null}
    </form>
  );
}
