import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { actionLabel } from "../../../entities/audit/labels";
import { auditChanges, scalarText } from "../../../entities/audit/changes";
import { RoleChangeSummary } from "../../../entities/role/RoleChangeSummary";
import type { AuditEntry, RoleChange, RoleSnapshot } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { actorText, entityHref, entityText } from "./describe";

import "./audit.css";

const isSnapshot = (value: unknown): value is RoleSnapshot =>
  typeof value === "object" && value !== null && "access" in value && "name" in value;

function roleChangeOf(entry: AuditEntry): Pick<RoleChange, "action" | "before" | "after"> | null {
  if (entry.entity_type !== "platform_role") return null;
  const action = entry.action.split(".").pop();
  if (action !== "create" && action !== "update" && action !== "delete") return null;
  const before = isSnapshot(entry.before) ? entry.before : undefined;
  const after = isSnapshot(entry.after) ? entry.after : undefined;
  return { action, ...(before ? { before } : {}), ...(after ? { after } : {}) };
}

function FieldChanges({ entry }: { entry: AuditEntry }) {
  const { t } = useTranslation("audit");
  const text = (value: unknown) => {
    if (typeof value === "boolean") return t(value ? "values.yes" : "values.no");
    return scalarText(value) ?? t("values.none");
  };
  const label = (path: string) => {
    const parts = path.split(".");
    const last = parts[parts.length - 1] ?? path;
    return t(`fields.${path}`, { defaultValue: t(`fields.${last}`, { defaultValue: path }) });
  };
  const changes = auditChanges(entry.before, entry.after);
  if (changes.length === 0) {
    return (
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("card.noChanges")}
      </p>
    );
  }
  return (
    <div>
      {changes.map((change) => (
        <div key={change.path} className="pf-audit-change">
          <span className="pf-audit-change-name">{label(change.path)}</span>
          {"before" in change ? (
            <span>
              <span className="pf-hint">{t("card.from")}: </span>
              {text(change.before)}
            </span>
          ) : null}
          {"after" in change ? (
            <span>
              <span className="pf-hint">{t("card.to")}: </span>
              {text(change.after)}
            </span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

/** Запись журнала в боковом окне: кто, когда, над чем и что именно изменилось (до → после). */
export function AuditEntryCard({
  entry,
  names,
}: {
  entry: AuditEntry;
  names: ReadonlyMap<string, string>;
}) {
  const { t } = useTranslation("audit");
  const format = useFormat();
  const href = entityHref(entry);
  const object = entityText(t, entry, names);
  const roleChange = roleChangeOf(entry);
  return (
    <div className="pf-panel-stack">
      <h3 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
        {actionLabel(t, entry.action)}
      </h3>
      <DefinitionList
        items={[
          { label: t("card.when"), value: format.date(entry.at, "datetime") },
          { label: t("card.actor"), value: actorText(t, entry, names) },
          {
            label: t("card.entity"),
            value: href ? (
              <Link
                className="pf-focusable"
                to={href}
                aria-label={t("card.open", { name: object })}
              >
                {object}
              </Link>
            ) : (
              object
            ),
          },
          { label: t("card.ip"), value: entry.ip },
        ]}
      />
      <h4 style={{ margin: 0, fontSize: 14, lineHeight: "22px", fontWeight: 600 }}>
        {t("card.changes")}
      </h4>
      {roleChange ? <RoleChangeSummary change={roleChange} /> : <FieldChanges entry={entry} />}
    </div>
  );
}
