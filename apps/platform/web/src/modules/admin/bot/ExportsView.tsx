import { App, Button, Card, Input, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { downloadFile } from "../../../shared/api/download";
import { getDownloadCsvExportUrl } from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { DateRangeField } from "../../../shared/ui/DateField";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { botErrorText } from "./errors";

type Entity = "leads" | "clients" | "deals";
const ENTITIES: readonly Entity[] = ["leads", "clients", "deals"];
/** Раздел каталога, чтение которого нужно для выгрузки (в CRM — `leads|clients|deals:read`). */
const DATA_SECTION: Record<Entity, string> = {
  leads: "crm.leads",
  clients: "crm.clients",
  deals: "crm.clients",
};

type Filters = Record<string, string>;

/** Дата без времени -> граница суток в Ташкенте (+05:00), чтобы «создан не позже 26.10» включал весь день. */
function dayStart(day: string): string {
  return `${day}T00:00:00+05:00`;
}
function dayEnd(day: string): string {
  return `${day}T23:59:59+05:00`;
}

function query(entity: Entity, filters: Filters) {
  const params: Record<string, string> = {};
  const text = (filters["q"] ?? "").trim();
  if (text && entity !== "deals") params["q"] = text;
  if (entity === "leads") {
    if (filters["language"]) params["language"] = filters["language"];
    if (filters["from"]) params["created_from"] = dayStart(filters["from"]);
    if (filters["to"]) params["created_to"] = dayEnd(filters["to"]);
  }
  if (entity === "deals") {
    if (filters["stage"]) params["stage"] = filters["stage"];
    if (filters["from"]) params["closed_from"] = filters["from"];
    if (filters["to"]) params["closed_to"] = filters["to"];
  }
  return params;
}

function ExportCard({ entity, allowed }: { entity: Entity; allowed: boolean }) {
  const { t } = useTranslation(["bot", "kb"]);
  const { message } = App.useApp();
  const [filters, setFilters] = useState<Filters>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (key: string, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };
  const id = `export-${entity}`;
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const name = await downloadFile(
        getDownloadCsvExportUrl(entity, query(entity, filters)),
        `${entity}.csv`,
      );
      void message.success(t("bot:exports.done", { name }));
    } catch (failure) {
      setError(botErrorText(t, failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <article className="pf-bot-export" data-entity={entity} aria-labelledby={`${id}-title`}>
      <h3 className="pf-bot-subtitle" id={`${id}-title`}>
        {t(`bot:exports.entities.${entity}.title`)}
      </h3>
      <p className="pf-fp-sub">{t(`bot:exports.entities.${entity}.purpose`)}</p>
      <form
        className="pf-fp-form"
        aria-label={t("bot:exports.formLabel", {
          title: t(`bot:exports.entities.${entity}.title`),
        })}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (allowed && !busy) void run();
        }}
      >
        {entity !== "deals" ? (
          <FormField id={`${id}-q`} label={t("bot:exports.filters.q")}>
            <Input
              id={`${id}-q`}
              value={filters["q"] ?? ""}
              maxLength={100}
              autoComplete="off"
              disabled={!allowed}
              onChange={(event) => {
                set("q", event.target.value);
              }}
            />
          </FormField>
        ) : (
          <FormField id={`${id}-stage`} label={t("bot:exports.filters.stage")}>
            <Select
              id={`${id}-stage`}
              allowClear
              disabled={!allowed}
              value={filters["stage"] || undefined}
              placeholder={t("bot:exports.filters.anyStage")}
              options={(["open", "won", "lost"] as const).map((value) => ({
                value,
                label: t(`bot:exports.dealStages.${value}`),
              }))}
              onChange={(value: string | undefined) => {
                set("stage", value ?? "");
              }}
            />
          </FormField>
        )}
        {entity === "leads" ? (
          <FormField id={`${id}-language`} label={t("bot:exports.filters.language")}>
            <Select
              id={`${id}-language`}
              allowClear
              disabled={!allowed}
              value={filters["language"] || undefined}
              placeholder={t("bot:exports.filters.anyLanguage")}
              options={(["ru", "uz", "en"] as const).map((value) => ({
                value,
                label: t(`kb:languages.${value}`),
              }))}
              onChange={(value: string | undefined) => {
                set("language", value ?? "");
              }}
            />
          </FormField>
        ) : null}
        {entity !== "clients" ? (
          <div className="pf-fp-row">
            <DateRangeField
              idFrom={`${id}-from`}
              idTo={`${id}-to`}
              labelFrom={t(`bot:exports.filters.from.${entity}`)}
              labelTo={t(`bot:exports.filters.to.${entity}`)}
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
        ) : null}
        {allowed ? null : (
          <p className="pf-hint" role="note">
            {t("bot:exports.needSection", {
              section: t(`bot:exports.sections.${DATA_SECTION[entity]}`),
            })}
          </p>
        )}
        <ErrorNote message={error} />
        <div className="pf-fp-row">
          <Button type="primary" htmlType="submit" loading={busy} disabled={!allowed}>
            {t("bot:exports.download", { title: t(`bot:exports.entities.${entity}.title`) })}
          </Button>
        </div>
      </form>
    </article>
  );
}

/** Выгрузки CSV лидов, клиентов и сделок: файл идёт потоком через BFF, имя содержит дату; нужен доступ к самим данным. */
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
        {editable ? (
          <Consequence items={[t("exports.step1"), t("exports.step2"), t("exports.step3")]} />
        ) : (
          <p className="pf-hint">{t("exports.readOnly")}</p>
        )}
        <div className="pf-bot-exports">
          {ENTITIES.map((entity) => (
            <ExportCard
              key={entity}
              entity={entity}
              allowed={editable && canSee(me, { resource: DATA_SECTION[entity] })}
            />
          ))}
        </div>
      </Card>
    </section>
  );
}
