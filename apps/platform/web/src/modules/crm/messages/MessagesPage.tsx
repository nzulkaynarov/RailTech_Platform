import { Alert, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { useListCrmMessages } from "../../../shared/api/generated/platform-bff";
import { usePollQuery } from "../../../shared/api/polling";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { LockIcon } from "../../../shared/ui/icons";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { Dialog } from "./Dialog";
import { InboxList } from "./InboxList";

import "./messages.css";

const LEAD = /^L-\d{4,}$/;

/**
 * Клиенты · Ждут ответа (SPEC-v3 §7.2 «Все сообщения», UX-оценка P0-5): передачи от бота с запиской и таймером SLA,
 * «Забрать», лента диалога и ответ «От себя / Заметка команде». Основное окно — список (≈280 px) и диалог, боковое — карточка
 * лида; на 390 px — список, затем диалог на весь экран. Живые обновления — подсказка `messages` потока BFF (без опроса;
 * опрос — страховка, `usePollQuery`). Директор (`crm.leads` — чтение) видит всё без «Забрать» и ответа.
 */
export function MessagesPage() {
  const { t } = useTranslation(["messages", "modules"]);
  const { me } = useAuth();
  const canReply = canEdit(me, "crm.leads");
  const { mobile } = useViewport();
  const [params] = useSearchParams();
  const raw = params.get("lead")?.toUpperCase() ?? null;
  const lead = raw && LEAD.test(raw) ? raw : null;
  const title = t("modules:crm.sections.messages");
  useDocumentTitle(title);
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
            <Dialog key={lead} lead={lead} item={item} canReply={canReply} mobile={mobile} />
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
      {mobile && lead ? null : (
        <PageHeader
          title={title}
          subtitle={t("messages:subtitle")}
          extra={
            canReply ? null : (
              <StatusTag tone="default">
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <LockIcon size={12} />
                  {t("messages:viewOnly")}
                </span>
              </StatusTag>
            )
          }
        />
      )}
      {body}
    </div>
  );
}
