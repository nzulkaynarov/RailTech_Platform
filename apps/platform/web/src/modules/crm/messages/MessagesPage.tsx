import { Alert, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { useListCrmMessages } from "../../../shared/api/generated/platform-bff";
import { usePollQuery } from "../../../shared/api/polling";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { LockIcon } from "../../../shared/ui/icons";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { Dialog } from "./Dialog";
import { InboxList } from "./InboxList";

import "./messages.css";

const LEAD = /^L-\d{4,}$/;

/**
 * Лиды · фильтр «Ждут ответа» (`/crm/leads?scope=waiting`, SPEC-v3 §7.2 «Все сообщения», UX-оценка P0-5): передачи от бота с запиской и таймером SLA,
 * «Забрать», лента диалога и ответ «От себя / Заметка команде». Основное окно — список (≈280 px) и диалог, боковое — карточка
 * лида; на 390 px — список, затем диалог на весь экран. Живые обновления — подсказка `messages` потока BFF (без опроса;
 * опрос — страховка, `usePollQuery`). Директор (`crm.leads` — чтение) видит всё без «Забрать» и ответа; делопроизводитель
 * (`crm.leads.triage`, D17G-1) — с «Передать менеджеру» и пояснением «Ответ клиенту — менеджер».
 */
export function Conversations() {
  const { t } = useTranslation(["messages", "modules"]);
  const { me } = useAuth();
  const canReply = canEdit(me, "crm.leads");
  // Первая линия (D17G-1): разбирает и передаёт менеджеру, клиенту не отвечает.
  const canTriage = !canReply && canEdit(me, "crm.leads.triage");
  const { mobile } = useViewport();
  const [params] = useSearchParams();
  const raw = params.get("lead")?.toUpperCase() ?? null;
  const lead = raw && LEAD.test(raw) ? raw : null;
  const poll = usePollQuery();
  const inbox = useListCrmMessages({ query: poll });
  const items = inbox.data?.items ?? [];
  const item = items.find((i) => i.lead === lead);

  let body;
  if (inbox.isPending) {
    body = (
      <div className="pf-msg-center">
        <Spin />
      </div>
    );
  } else if (inbox.isError) {
    body = (
      <Alert
        type="error"
        showIcon
        message={t("messages:loadFailed")}
        action={
          <Button size="small" onClick={() => void inbox.refetch()}>
            {t("messages:reload")}
          </Button>
        }
      />
    );
  } else if (!items.length && !lead) {
    body = (
      <EmptyState
        title={t("messages:list.empty.title")}
        text={t("messages:list.empty.text")}
        action={<LinkButton to="/crm/leads">{t("messages:list.empty.action")}</LinkButton>}
      />
    );
  } else {
    const showList = !mobile || !lead;
    const showDialog = !mobile || Boolean(lead);
    body = (
      <div className={mobile ? "pf-msg pf-msg--mobile" : "pf-msg"}>
        {showList ? <InboxList items={items} selected={lead} canReply={canReply} /> : null}
        {showDialog ? (
          lead ? (
            <Dialog
              key={lead}
              lead={lead}
              item={item}
              canReply={canReply}
              canTriage={canTriage}
              mobile={mobile}
            />
          ) : (
            <section className="pf-msg-dialog">
              <EmptyState
                compact
                title={t("messages:thread.select.title")}
                text={t("messages:thread.select.text")}
              />
            </section>
          )
        ) : null}
      </div>
    );
  }

  return (
    <div className="pf-msg-page">
      {canReply || (mobile && lead) ? null : (
        <StatusTag tone="default">
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <LockIcon size={12} />
            {t(canTriage ? "messages:triageOnly" : "messages:viewOnly")}
          </span>
        </StatusTag>
      )}
      {body}
    </div>
  );
}
