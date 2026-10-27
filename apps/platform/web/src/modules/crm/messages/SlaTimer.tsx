import { useTranslation } from "react-i18next";

import type { HandoffInfo } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { durationParts, slaState } from "./sla";

/**
 * Таймер SLA передачи: «ждёт 12 мин»; после срока реакции — красный и со словом «срок прошёл» (статус не только цветом,
 * SPEC-v3 §5.3). Отложенная передача — «отложено до 14:20», забранная — «забрал …». `now` передаёт список (один таймер
 * на экран, а не по таймеру на строку).
 */
export function SlaTimer({ handoff, now }: { handoff: HandoffInfo; now: number }) {
  const { t } = useTranslation("messages");
  const fmt = useFormat();
  if (handoff.state === "snoozed" && handoff.snoozed_until) {
    return (
      <span className="pf-msg-sla">
        {t("sla.snoozed", { time: fmt.activity(handoff.snoozed_until, new Date(now)) })}
      </span>
    );
  }
  if (handoff.state === "taken" && handoff.taken_by) {
    return <span className="pf-msg-sla">{t("sla.taken", { name: handoff.taken_by.name })}</span>;
  }
  const state = slaState(handoff, now);
  const { key, values } = durationParts(state.minutes);
  const waiting = t("sla.waiting", { duration: t(`duration.${key}`, values) });
  return (
    <span
      className={state.overdue ? "pf-msg-sla pf-msg-sla--overdue" : "pf-msg-sla"}
      data-overdue={state.overdue}
    >
      {waiting}
      {state.overdue ? ` · ${t("sla.overdue")}` : null}
    </span>
  );
}
