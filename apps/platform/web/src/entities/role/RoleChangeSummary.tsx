import { useTranslation } from "react-i18next";

import type { RoleChange } from "../../shared/api/generated/model";
import { fieldLabel, sectionFullLabel } from "./roles";
import { isEmptyDiff, roleDiff } from "./diff";

/** Что изменилось в роли — списком строк словами: название, описание, уровни разделов, поля с ограничением. */
export function RoleChangeSummary({
  change,
}: {
  change: Pick<RoleChange, "action" | "before" | "after">;
}) {
  const { t, i18n } = useTranslation("audit");
  const level = (value?: string) => t(`role.level.${value ?? "hidden"}`);
  const section = (key: string) => sectionFullLabel(key, i18n.language);

  if (change.action === "delete") return <p style={{ margin: 0 }}>{t("role.deleted")}</p>;

  const diff = roleDiff(change.action === "create" ? undefined : change.before, change.after);
  const lines: string[] = [];
  if (change.action === "create") {
    for (const s of diff.sections) {
      lines.push(t("role.sectionNew", { section: section(s.resource), to: level(s.to) }));
    }
    for (const f of diff.fields) {
      lines.push(t("role.fieldShown", { field: fieldLabel(f.field, i18n.language) }));
    }
  } else {
    if (diff.name) lines.push(t("role.renamed", { from: diff.name.from, to: diff.name.to }));
    if (diff.description) lines.push(t("role.descriptionChanged"));
    for (const s of diff.sections) {
      lines.push(
        t("role.section", { section: section(s.resource), from: level(s.from), to: level(s.to) }),
      );
    }
    for (const f of diff.fields) {
      lines.push(
        t(f.visible ? "role.fieldShown" : "role.fieldHidden", {
          field: fieldLabel(f.field, i18n.language),
        }),
      );
    }
  }
  if (lines.length === 0) {
    return (
      <p className="pf-hint" style={{ margin: 0 }}>
        {t(isEmptyDiff(diff) && change.action === "create" ? "role.noSections" : "role.nothing")}
      </p>
    );
  }
  return (
    <ul className="pf-audit-lines">
      {lines.map((line, index) => (
        <li key={index}>{line}</li>
      ))}
    </ul>
  );
}
