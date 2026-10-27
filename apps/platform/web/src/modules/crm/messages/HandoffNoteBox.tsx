import { useTranslation } from "react-i18next";

import type { HandoffInfo, HandoffNote } from "../../../shared/api/generated/model";
import { factRows, reasonLabels } from "./labels";

/**
 * Записка передачи (CRM-06) над лентой диалога: запрос, причина, рекомендуемый шаг, факты — чтобы ответить, не листая
 * переписку. Пустые строки не показываются.
 */
export function HandoffNoteBox({
  note,
  handoff,
}: {
  note: HandoffNote;
  handoff: HandoffInfo | null;
}) {
  const { t } = useTranslation("messages");
  const reasons = handoff ? reasonLabels(t, handoff.reasons) : [];
  const reason = [...reasons, handoff?.reason_text].filter(Boolean).join("; ");
  const facts = factRows(t, note.facts);
  const rows: { label: string; value: string }[] = [];
  if (note.request) rows.push({ label: t("note.request"), value: note.request });
  if (reason) rows.push({ label: t("note.reason"), value: reason });
  if (handoff?.recommendation) rows.push({ label: t("note.next"), value: handoff.recommendation });
  if (facts.length)
    rows.push({
      label: t("note.facts"),
      value: facts.map((f) => `${f.label}: ${f.value}`).join(" · "),
    });
  if (!rows.length) return null;
  return (
    <section className="pf-msg-note" aria-label={t("note.title")}>
      <h3 className="pf-msg-note-title">{t("note.title")}</h3>
      <dl className="pf-msg-note-list">
        {rows.map((row) => (
          <div key={row.label} className="pf-msg-note-row">
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
