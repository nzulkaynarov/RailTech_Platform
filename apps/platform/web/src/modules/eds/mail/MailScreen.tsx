import { keepPreviousData } from "@tanstack/react-query";
import { Card, Segmented, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { InboundMailItem } from "../../../shared/api/generated/model";
import { useListInboundMail } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { TabsBar } from "../../../shared/ui/TabsBar";
import { MailView } from "./MailView";
import { ADMIN_MAIL_PATH, arrivedAt, mailPath } from "./mailModel";

import "../inbox/inbox.css";
import "./mail.css";

function Row({ mail }: { mail: InboundMailItem }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const subject = mail.subject || t("mail.noSubject");
  const kind = mail.assist.status === "done" && mail.assist.kind ? mail.assist.kind : null;
  return (
    <li className="pf-mail-row">
      <div className="pf-mail-row-head">
        <Link
          className="pf-focusable pf-mail-subject"
          to={mailPath(mail.id)}
          aria-label={t("mail.open", { subject })}
        >
          {subject}
        </Link>
        <span className="pf-hint">{date(arrivedAt(mail), "datetime")}</span>
      </div>
      <p className="pf-mail-sender">
        {mail.from_name ? `${mail.from_name} · ${mail.from_email}` : mail.from_email}
        {mail.client ? ` · ${mail.client.name}` : ""}
      </p>
      <p className="pf-hint pf-mail-preview">{mail.assist.summary ?? mail.preview}</p>
      <div className="pf-fp-row">
        {mail.from_history ? <StatusTag tone="default">{t("mail.historyTag")}</StatusTag> : null}
        {kind ? <StatusTag tone="blue">{t(`mail.kind.${kind}`)}</StatusTag> : null}
        {mail.attachments_count > 0 ? (
          <span className="pf-hint">
            {t("mail.attachments", { count: mail.attachments_count })}
          </span>
        ) : null}
      </div>
    </li>
  );
}

type Tab = "new" | "spam";
type Show = "all" | "history";

function MailList() {
  const { t } = useTranslation(["letters", "modules"]);
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "spam" ? "spam" : "new";
  const show: Show = tab === "new" && params.get("show") === "history" ? "history" : "all";
  const query = useListInboundMail(
    { status: tab, ...(show === "history" ? { history: true } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const title = t("modules:eds.sections.mail");
  useDocumentTitle(title);
  const data = query.data;
  const go = (next: { tab?: Tab; show?: Show }) => {
    const nextTab = next.tab ?? tab;
    const nextShow = nextTab === "new" ? (next.show ?? (next.tab ? "all" : show)) : "all";
    const search = new URLSearchParams();
    if (nextTab === "spam") search.set("tab", "spam");
    if (nextShow === "history") search.set("show", "history");
    setParams(search, { replace: true });
  };
  const caption = tab === "spam" ? t("letters:mail.spamCaption") : t("letters:mail.caption");
  let body;
  if (query.isPending) {
    body = <Skeleton active paragraph={{ rows: 6 }} />;
  } else if (!data) {
    body = (
      <EmptyState
        title={t("letters:state.loadError.title")}
        text={t("letters:state.loadError.text")}
      />
    );
  } else if (!data.mailbox.configured) {
    body = (
      <EmptyState
        title={t("letters:mail.off.title")}
        text={t("letters:mail.off.text")}
        action={
          canSee(me, { resource: "admin" }) ? (
            <LinkButton to={ADMIN_MAIL_PATH}>{t("letters:mail.off.action")}</LinkButton>
          ) : undefined
        }
      />
    );
  } else if (data.items.length === 0) {
    const empty = tab === "spam" ? "spamEmpty" : show === "history" ? "historyEmpty" : "empty";
    body = (
      <EmptyState title={t(`letters:mail.${empty}.title`)} text={t(`letters:mail.${empty}.text`)} />
    );
  } else {
    body = (
      <ul className="pf-mail-list" aria-label={caption}>
        {data.items.map((mail) => (
          <Row key={mail.id} mail={mail} />
        ))}
      </ul>
    );
  }
  const counts = data?.counts;
  const label = (key: Tab) => {
    const count = counts ? (key === "spam" ? counts.spam : counts.new) : null;
    return count === null
      ? t(`letters:mail.tabs.${key}`)
      : `${t(`letters:mail.tabs.${key}`)} · ${String(count)}`;
  };
  return (
    <div className="pf-mail">
      <PageHeader title={title} subtitle={t("letters:mail.subtitle")} />
      <Card styles={{ body: { padding: 0 } }}>
        <TabsBar
          id="pf-mail-tabs"
          label={t("letters:mail.tabs.label")}
          activeKey={tab}
          onChange={(key) => {
            go({ tab: key === "spam" ? "spam" : "new" });
          }}
          tabBarStyle={{ margin: 0, padding: "0 16px" }}
          items={(["new", "spam"] as const).map((key) => ({ key, label: label(key) }))}
        >
          <div className="pf-mail-body">
            {tab === "new" ? (
              <Segmented<Show>
                aria-label={t("letters:mail.filter.label")}
                value={show}
                onChange={(value) => {
                  go({ show: value });
                }}
                options={[
                  { value: "all", label: t("letters:mail.filter.all") },
                  {
                    value: "history",
                    label: counts
                      ? `${t("letters:mail.filter.history")} · ${String(counts.history)}`
                      : t("letters:mail.filter.history"),
                  },
                ]}
              />
            ) : (
              <p className="pf-hint pf-mail-what">{t("letters:mail.spamIntro")}</p>
            )}
            {body}
          </div>
        </TabsBar>
      </Card>
    </div>
  );
}

/** Документы · Входящая почта (W18A-P2): очередь `/eds/mail` или карточка письма `/eds/mail/:id`. */
export function MailScreen({ objectId }: { objectId?: string | undefined }) {
  const id = Number(objectId);
  return objectId && Number.isInteger(id) && id > 0 ? <MailView id={id} /> : <MailList />;
}
