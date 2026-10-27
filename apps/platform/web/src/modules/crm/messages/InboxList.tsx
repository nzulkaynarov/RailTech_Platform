import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { MessageInboxItem, MessageInboxItemGroup } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { withParams } from "../kb/refresh";
import { useLeadActions } from "./actions";
import { canTake } from "./logic";
import { PRIORITY_TONE, reasonLabels } from "./labels";
import { SlaTimer } from "./SlaTimer";
import { useNow } from "./sla";

const GROUPS: MessageInboxItemGroup[] = ["handoff", "mine", "unassigned"];

function TakeButton({ lead, name }: { lead: string; name: string }) {
  const { t } = useTranslation("messages");
  const actions = useLeadActions(lead);
  return (
    <Button
      size="small"
      type="primary"
      loading={actions.taking}
      onClick={actions.take}
      aria-label={`${t("actions.take")}: ${name}`}
    >
      {t("actions.take")}
    </Button>
  );
}

function Row({
  item,
  active,
  canReply,
  now,
}: {
  item: MessageInboxItem;
  active: boolean;
  canReply: boolean;
  now: number;
}) {
  const { t } = useTranslation("messages");
  const [params] = useSearchParams();
  // На 390 px карточка лида — свой лист из диалога, боковое окно каркаса не открываем.
  const { mobile } = useViewport();
  const summary = item.note.request ?? item.note.last_message ?? t("list.noRequest");
  const reasons = item.handoff ? reasonLabels(t, item.handoff.reasons) : [];
  return (
    <li className={active ? "pf-msg-row pf-msg-row--active" : "pf-msg-row"}>
      <Link
        className="pf-msg-row-link"
        to={withParams(params, { lead: item.lead, panel: mobile ? null : "open" })}
        aria-current={active ? "true" : undefined}
      >
        <span className="pf-msg-row-head">
          <span className="pf-msg-row-name">{item.name}</span>
          {item.unread ? <span className="pf-msg-unread">{t("list.unread")}</span> : null}
        </span>
        <span className="pf-msg-row-summary">{summary}</span>
        {reasons.length ? <span className="pf-msg-row-reasons">{reasons.join(" · ")}</span> : null}
      </Link>
      <span className="pf-msg-row-meta">
        {item.handoff ? (
          <StatusTag tone={PRIORITY_TONE[item.handoff.priority]}>
            {t(`priority.${item.handoff.priority}`)}
          </StatusTag>
        ) : null}
        {item.handoff ? (
          <SlaTimer handoff={item.handoff} now={now} />
        ) : item.assigned ? (
          <span className="pf-msg-sla">{t("list.takenBy", { name: item.assigned.name })}</span>
        ) : null}
        {canReply && canTake(item) ? <TakeButton lead={item.lead} name={item.name} /> : null}
      </span>
    </li>
  );
}

/**
 * Список «Ждут ответа» (≈280 px): группы «Передачи от бота», «Мои диалоги», «Без менеджера». Строка — ссылка на диалог
 * (`?lead=L-NNNN`), под ней — приоритет словом, таймер SLA и «Забрать» (только с правом ответа).
 */
export function InboxList({
  items,
  selected,
  canReply,
}: {
  items: MessageInboxItem[];
  selected: string | null;
  canReply: boolean;
}) {
  const { t } = useTranslation("messages");
  const now = useNow();
  return (
    <nav className="pf-msg-list" aria-label={t("list.label")}>
      {GROUPS.map((group) => {
        const rows = items.filter((i) => i.group === group);
        if (!rows.length) return null;
        const id = `pf-msg-group-${group}`;
        return (
          <section key={group} aria-labelledby={id}>
            <h2 id={id} className="pf-msg-group">
              {t(`list.groups.${group}`)} · {rows.length}
            </h2>
            <ul className="pf-msg-rows">
              {rows.map((item) => (
                <Row
                  key={item.lead}
                  item={item}
                  active={item.lead === selected}
                  canReply={canReply}
                  now={now}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </nav>
  );
}
