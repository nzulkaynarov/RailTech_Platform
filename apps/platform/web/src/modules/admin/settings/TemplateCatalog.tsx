import { Alert, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { TemplateKind, TemplateRow } from "../../../shared/api/generated/model";
import { useListTemplateCatalog } from "../../../shared/api/generated/platform-bff";
import type { DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { RegistryTable } from "../../../shared/ui/RegistryTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { FilterBar, FilterField } from "../../../shared/ui/FilterBar";

const LANGS = ["ru", "uz", "en"] as const;

/**
 * «Все шаблоны» (план 2.7, исследование 2026-11-11 «Документы и шаблоны» §3): шаблоны документов, писем, резолюций и
 * ответов бота одной таблицей. Языки — RU UZ EN, отсутствующий бледный; метка — образец платформы, свой или выключен.
 * Строка ведёт в редактор своего вида.
 */
export function TemplateCatalog() {
  const { t } = useTranslation("company");
  const query = useListTemplateCatalog();
  const [kind, setKind] = useState<TemplateKind | null>(null);
  const items = query.data?.items ?? [];
  const kinds = [...new Set(items.map((row) => row.kind))];
  const rows = kind ? items.filter((row) => row.kind === kind) : items;
  const down = Object.entries(query.data?.sources ?? {}).filter(
    ([, state]) => state === "unavailable",
  );

  const columns: DataColumn<TemplateRow>[] = [
    {
      id: "name",
      header: t("catalog.columns.name"),
      width: null,
      cellClassName: "pf-ell",
      cellTitle: (row) => row.name,
      cell: (row) => (
        <Link className="pf-focusable" to={row.path}>
          {row.name}
        </Link>
      ),
    },
    {
      id: "kind",
      header: t("catalog.columns.kind"),
      width: 180,
      cell: (row) => t(`catalog.kinds.${row.kind}`),
    },
    {
      id: "languages",
      header: t("catalog.columns.languages"),
      width: 132,
      cell: (row) =>
        row.languages.length === 0 ? (
          "—"
        ) : (
          <span>
            <span className="pf-sr-only">
              {row.languages.map((l) => l.toUpperCase()).join(", ")}
            </span>
            {LANGS.map((lang) => (
              <span
                key={lang}
                aria-hidden
                className={
                  row.languages.includes(lang) ? "pf-tpl-lang" : "pf-tpl-lang pf-tpl-lang-off"
                }
              >
                {lang.toUpperCase()}
              </span>
            ))}
          </span>
        ),
    },
    {
      id: "label",
      header: t("catalog.columns.label"),
      width: 132,
      cell: (row) =>
        !row.active ? (
          <StatusTag tone="default">{t("catalog.labels.off")}</StatusTag>
        ) : row.origin === "builtin" ? (
          <StatusTag tone="blue">{t("catalog.labels.builtin")}</StatusTag>
        ) : null,
    },
  ];

  return (
    <div className="pf-fp-stack">
      {down.length > 0 ? <Alert type="warning" showIcon message={t("catalog.partial")} /> : null}
      <RegistryTable<TemplateRow>
        tableId="admin.templates"
        caption={t("catalog.caption")}
        scrollLabel={t("catalog.scroll")}
        flexMin={220}
        nested
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id}
        loading={query.isPending}
        error={
          query.isError ? (
            <EmptyState
              level={3}
              compact
              title={t("catalog.error")}
              text={t("catalog.errorText")}
            />
          ) : undefined
        }
        empty={
          <EmptyState level={3} compact title={t("catalog.empty")} text={t("catalog.emptyText")} />
        }
        toolbar={
          <FilterBar inset tools>
            <FilterField id="pf-tpl-kind" label={t("catalog.filter")} width={240}>
              <Select
                id="pf-tpl-kind"
                allowClear
                placeholder={t("catalog.all")}
                value={kind}
                onChange={(value: TemplateKind | undefined) => {
                  setKind(value ?? null);
                }}
                options={kinds.map((value) => ({ value, label: t(`catalog.kinds.${value}`) }))}
              />
            </FilterField>
          </FilterBar>
        }
      />
    </div>
  );
}
