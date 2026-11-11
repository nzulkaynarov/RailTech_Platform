import { App, Button, Card, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { downloadFile } from "../../../shared/api/download";
import { getDownloadCsvExportUrl } from "../../../shared/api/generated/platform-bff";
import { DateRangeField } from "../../../shared/ui/DateField";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { botErrorText } from "./errors";

/** Выгружаются только сделки, без контактов (решение владельца 2026-11-11): лиды и клиенты — персональные данные. */
const ENTITY = "deals";
/** Раздел каталога, чтение которого нужно для выгрузки (в CRM — `deals:read`). */
const DATA_SECTION = "crm.clients";

type Filters = Record<string, string>;

function query(filters: Filters) {
  const params: Record<string, string> = {};
  if (filters["stage"]) params["stage"] = filters["stage"];
  if (filters["from"]) params["closed_from"] = filters["from"];
  if (filters["to"]) params["closed_to"] = filters["to"];
  return params;
}

function DealsExport({ allowed }: { allowed: boolean }) {
  const { t } = useTranslation("bot");
  const { message } = App.useApp();
  const [filters, setFilters] = useState<Filters>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (key: string, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };
  const id = `export-${ENTITY}`;
  const title = t(`exports.entities.${ENTITY}.title`);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const name = await downloadFile(
        getDownloadCsvExportUrl(ENTITY, query(filters)),
        `${ENTITY}.csv`,
      );
      void message.success(t("exports.done", { name }));
    } catch (failure) {
      setError(botErrorText(t, failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <article className="pf-bot-export" data-entity={ENTITY} aria-labelledby={`${id}-title`}>
      <h3 className="pf-bot-subtitle" id={`${id}-title`}>
        {title}
      </h3>
      <p className="pf-fp-sub">{t(`exports.entities.${ENTITY}.purpose`)}</p>
      <form
        className="pf-fp-form"
        aria-label={t("exports.formLabel", { title })}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (allowed && !busy) void run();
        }}
      >
        <FormField id={`${id}-stage`} label={t("exports.filters.stage")}>
          <Select
            id={`${id}-stage`}
            allowClear
            disabled={!allowed}
            value={filters["stage"] || undefined}
            placeholder={t("exports.filters.anyStage")}
            options={(["open", "won", "lost"] as const).map((value) => ({
              value,
              label: t(`exports.dealStages.${value}`),
            }))}
            onChange={(value: string | undefined) => {
              set("stage", value ?? "");
            }}
          />
        </FormField>
        <div className="pf-fp-row">
          <DateRangeField
            idFrom={`${id}-from`}
            idTo={`${id}-to`}
            labelFrom={t("exports.filters.from.deals")}
            labelTo={t("exports.filters.to.deals")}
            disabled={!allowed}
            value={{ from: filters["from"] ?? "", to: filters["to"] ?? "" }}
            wrap={({ id: fieldId, label, children }) => (
              <FormField id={fieldId} label={label}>
                {children}
              </FormField>
            )}
            onChange={(range) => {
              if (range.from !== (filters["from"] ?? "")) set("from", range.from);
              if (range.to !== (filters["to"] ?? "")) set("to", range.to);
            }}
          />
        </div>
        {allowed ? null : (
          <p className="pf-hint" role="note">
            {t("exports.needSection", { section: t(`exports.sections.${DATA_SECTION}`) })}
          </p>
        )}
        <ErrorNote message={error} />
        <div className="pf-fp-row">
          <Button type="primary" htmlType="submit" loading={busy} disabled={!allowed}>
            {t("exports.download", { title })}
          </Button>
        </div>
      </form>
    </article>
  );
}

/** Выгрузка CSV сделок: файл идёт потоком через BFF, имя содержит дату; нужен доступ к самим данным. */
export function ExportsView() {
  const { t } = useTranslation("bot");
  const { me } = useAuth();
  const editable = canEdit(me, "admin");
  return (
    <section aria-labelledby="pf-bot-exports">
      <Card
        title={
          <h2 className="pf-bot-section-title" id="pf-bot-exports">
            {t("exports.title")}
          </h2>
        }
        styles={{ body: { display: "flex", flexDirection: "column", gap: 16 } }}
      >
        <p className="pf-fp-sub">{t("exports.intro")}</p>
        {editable ? null : <p className="pf-hint">{t("exports.readOnly")}</p>}
        <div className="pf-bot-exports">
          <DealsExport allowed={editable && canSee(me, { resource: DATA_SECTION })} />
        </div>
      </Card>
    </section>
  );
}
