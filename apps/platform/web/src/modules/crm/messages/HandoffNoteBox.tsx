import { Button, Dropdown } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  HandoffInfo,
  HandoffNote,
  SnoozeLeadInPeriod,
} from "../../../shared/api/generated/model";
import {
  useAcknowledgeCrmLead,
  useSnoozeCrmLead,
  useUnsnoozeCrmLead,
} from "../../../shared/api/generated/platform-bff";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { useRefreshMessages } from "./actions";
import { actionError, factRows, reasonLabels } from "./labels";

const PERIODS: readonly SnoozeLeadInPeriod[] = ["hour", "day", "three_days"];

/**
 * «Принято к сведению», «Отложить» и «Вернуть из отложенных» (LH-1): информационную передачу закрывает отметка, срочную —
 * «Забрать». Состояние меняется на экране (строка уходит из «Ждут ответа» или получает срок), без всплывающих сообщений;
 * отказ CRM — строкой под кнопками.
 */
function HandoffActions({ lead, handoff }: { lead: string; handoff: HandoffInfo }) {
  const { t } = useTranslation("messages");
  const refresh = useRefreshMessages();
  const [failure, setFailure] = useState<string | null>(null);
  const mutation = {
    onSuccess: () => {
      setFailure(null);
      refresh();
    },
    onError: (error: unknown) => {
      setFailure(actionError(t, error));
    },
  };
  const acknowledge = useAcknowledgeCrmLead({ mutation });
  const snooze = useSnoozeCrmLead({ mutation });
  const unsnooze = useUnsnoozeCrmLead({ mutation });
  const busy = acknowledge.isPending || snooze.isPending || unsnooze.isPending;
  if (handoff.state === "taken") return null;
  return (
    <div className="pf-msg-note-actions">
      {handoff.priority === "info" ? (
        <Button
          size="small"
          loading={acknowledge.isPending}
          onClick={() => {
            acknowledge.mutate({ lead });
          }}
        >
          {t("note.acknowledge")}
        </Button>
      ) : null}
      {handoff.state === "snoozed" ? (
        <Button
          size="small"
          loading={unsnooze.isPending}
          onClick={() => {
            unsnooze.mutate({ lead });
          }}
        >
          {t("note.unsnooze")}
        </Button>
      ) : (
        <Dropdown
          trigger={["click"]}
          disabled={busy}
          menu={{
            items: PERIODS.map((period) => ({
              key: period,
              label: t(`note.snoozePeriods.${period}`),
            })),
            onClick: ({ key }) => {
              snooze.mutate({ lead, data: { period: key as SnoozeLeadInPeriod } });
            },
          }}
        >
          <Button size="small" loading={snooze.isPending}>
            {t("note.snooze")}
          </Button>
        </Dropdown>
      )}
      <ErrorNote message={failure} />
    </div>
  );
}

/**
 * Записка передачи (CRM-06) над лентой диалога: запрос, причина, рекомендуемый шаг, факты — чтобы ответить, не листая
 * переписку. Пустые строки не показываются.
 */
export function HandoffNoteBox({
  note,
  handoff,
  lead,
  canAct = false,
}: {
  note: HandoffNote;
  handoff: HandoffInfo | null;
  /** Номер лида и право `crm.leads: full` — без них кнопок нет */
  lead?: string;
  canAct?: boolean;
}) {
  const { t } = useTranslation("messages");
  const reasons = handoff ? reasonLabels(t, handoff.reasons) : [];
  const reason = [...reasons, handoff?.reason_text].filter(Boolean).join("; ");
  const facts = factRows(t, note.facts);
  const rows: { label: string; value: string }[] = [];
  // Передача первой линией (D17G-1): кто передал и тип обращения — первыми, записка — в «Причине».
  if (handoff?.handed_by) rows.push({ label: t("note.handedBy"), value: handoff.handed_by.name });
  if (handoff?.request_type)
    rows.push({ label: t("note.requestType"), value: t(`requestTypes.${handoff.request_type}`) });
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
      {canAct && lead && handoff ? <HandoffActions lead={lead} handoff={handoff} /> : null}
    </section>
  );
}
