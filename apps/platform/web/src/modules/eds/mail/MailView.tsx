import { Alert, App, Button, Card, Input, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { ApiError } from "../../../shared/api/errors";
import type { InboundMail, InboundMailAssistAction } from "../../../shared/api/generated/model";
import {
  archiveInboundMail,
  assistInboundMail,
  createLeadFromInboundMail,
  getDownloadInboundMailAttachmentUrl,
  replyInboundMail,
  useGetInboundMail,
} from "../../../shared/api/generated/platform-bff";
import { formatFileSize } from "../../../shared/lib/fileSize";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { registerFromMailPath, useRefreshMail } from "./mailModel";

type Step = "lead" | "archive" | null;

function reasonOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function Assist({ mail, onChange }: { mail: InboundMail; onChange: () => void }) {
  const { t } = useTranslation("letters");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { assist } = mail;
  if (assist.status === "off") return null;
  const ask = async () => {
    setPending(true);
    setError(null);
    try {
      await assistInboundMail(mail.id);
      onChange();
    } catch (failure) {
      setError(reasonOf(failure, t("mail.assist.unavailable")));
    } finally {
      setPending(false);
    }
  };
  return (
    <section aria-labelledby="mail-assist-title" className="pf-mail-actions">
      <h3 id="mail-assist-title" className="pf-res-subhead">
        {t("mail.assist.title")}
      </h3>
      {assist.status === "done" && assist.kind ? (
        <>
          <div className="pf-fp-row">
            <StatusTag tone="blue">{t(`mail.kind.${assist.kind}`)}</StatusTag>
          </div>
          {assist.summary ? <p className="pf-mail-what">{assist.summary}</p> : null}
          {assist.action ? (
            <p className="pf-mail-what">
              {t("mail.assist.suggests", { action: t(`mail.action.${assist.action}`) })}
            </p>
          ) : null}
          <p className="pf-hint pf-mail-what">{t("mail.assist.note")}</p>
        </>
      ) : (
        <>
          <p className="pf-hint pf-mail-what">
            {assist.status === "unavailable"
              ? t("mail.assist.unavailable")
              : t("mail.assist.intro")}
          </p>
          <div>
            <Button loading={pending} onClick={() => void ask()}>
              {assist.status === "unavailable" ? t("mail.assist.retry") : t("mail.assist.button")}
            </Button>
          </div>
        </>
      )}
      {error ? <Alert type="warning" showIcon role="status" message={error} /> : null}
    </section>
  );
}

function Actions({ mail, onDone }: { mail: InboundMail; onDone: () => void }) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(null);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const suggested: InboundMailAssistAction =
    mail.assist.status === "done" && mail.assist.action ? mail.assist.action : "register";
  const run = async (work: () => Promise<string>) => {
    setPending(true);
    setError(null);
    try {
      void message.success(await work());
      onDone();
      void navigate("/eds/mail");
    } catch (failure) {
      setError(t("mail.actions.failed", { reason: reasonOf(failure, String(failure)) }));
    } finally {
      setPending(false);
    }
  };
  const kind = (action: InboundMailAssistAction) => (action === suggested ? "primary" : "default");
  return (
    <section aria-labelledby="mail-actions-title" className="pf-mail-actions">
      <h3 id="mail-actions-title" className="pf-res-subhead">
        {t("mail.actions.title")}
      </h3>
      <div className="pf-fp-row">
        <LinkButton type={kind("register")} to={registerFromMailPath(mail.id)}>
          {t("mail.action.register")}
        </LinkButton>
        <Button
          type={kind("lead")}
          onClick={() => {
            setStep("lead");
          }}
        >
          {t("mail.action.lead")}
        </Button>
        <Button
          type={kind("archive")}
          onClick={() => {
            setStep("archive");
          }}
        >
          {t("mail.action.archive")}
        </Button>
      </div>
      <p className="pf-hint pf-mail-what">{t("mail.actions.registerWhat")}</p>
      {step === "lead" ? (
        <div className="pf-mail-actions">
          <Consequence title={t("mail.actions.what")} items={[t("mail.actions.leadWhat")]} />
          <div className="pf-fp-row">
            <Button
              type="primary"
              loading={pending}
              onClick={() =>
                void run(async () => {
                  const out = await createLeadFromInboundMail(mail.id);
                  return t(out.created ? "mail.actions.leadDone" : "mail.actions.leadNote", {
                    number: out.lead_number,
                  });
                })
              }
            >
              {t("mail.actions.leadConfirm")}
            </Button>
            <Button
              onClick={() => {
                setStep(null);
              }}
            >
              {t("mail.actions.cancel")}
            </Button>
          </div>
        </div>
      ) : null}
      {step === "archive" ? (
        <div className="pf-mail-actions">
          <label htmlFor="mail-archive-reason">{t("mail.actions.archiveReason")}</label>
          <Input
            id="mail-archive-reason"
            value={reason}
            maxLength={500}
            placeholder={t("mail.actions.archiveHint")}
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
          <Consequence title={t("mail.actions.what")} items={[t("mail.actions.archiveWhat")]} />
          <div className="pf-fp-row">
            <Button
              type="primary"
              loading={pending}
              disabled={reason.trim().length < 3}
              onClick={() =>
                void run(async () => {
                  await archiveInboundMail(mail.id, { reason: reason.trim() });
                  return t("mail.actions.archived");
                })
              }
            >
              {t("mail.actions.archiveConfirm")}
            </Button>
            <Button
              onClick={() => {
                setStep(null);
              }}
            >
              {t("mail.actions.cancel")}
            </Button>
          </div>
        </div>
      ) : null}
      {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
    </section>
  );
}

function Result({ mail }: { mail: InboundMail }) {
  const { t } = useTranslation("letters");
  if (mail.status === "registered" && mail.letter_number) {
    return (
      <div className="pf-mail-actions">
        <p className="pf-mail-what">
          {t("mail.result.registered", { number: mail.letter_number })}
        </p>
        {mail.letter_ref ? (
          <LinkButton to={mail.letter_ref}>
            {t("mail.result.openLetter", { number: mail.letter_number })}
          </LinkButton>
        ) : null}
      </div>
    );
  }
  if (mail.status === "lead" && mail.result_lead) {
    const number = mail.result_lead.number;
    return (
      <div className="pf-mail-actions">
        <p className="pf-mail-what">{t("mail.result.lead", { number })}</p>
        <LinkButton to={`/crm/leads?lead=${encodeURIComponent(number)}&panel=open&tab=card`}>
          {t("mail.result.openLead")}
        </LinkButton>
      </div>
    );
  }
  return (
    <p className="pf-mail-what">
      {t("mail.result.archived", { reason: mail.archive_reason ?? "—" })}
    </p>
  );
}

function Reply({ mail, onSent }: { mail: InboundMail; onSent: () => void }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const { message } = App.useApp();
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const send = async () => {
    setPending(true);
    setError(null);
    try {
      await replyInboundMail(mail.id, { text: text.trim() });
      setText("");
      void message.success(t("mail.reply.sent"));
      onSent();
    } catch (failure) {
      setError(t("mail.actions.failed", { reason: reasonOf(failure, String(failure)) }));
    } finally {
      setPending(false);
    }
  };
  return (
    <Card size="small" title={<h2 className="pf-letters-title">{t("mail.reply.title")}</h2>}>
      <div className="pf-mail-actions">
        <label htmlFor="mail-reply-text">{t("mail.reply.label")}</label>
        <Input.TextArea
          id="mail-reply-text"
          rows={4}
          maxLength={20000}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        <p className="pf-hint pf-mail-what">{t("mail.reply.what")}</p>
        <div>
          <Button loading={pending} disabled={!text.trim()} onClick={() => void send()}>
            {t("mail.reply.send")}
          </Button>
        </div>
        {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
        {mail.replies.length > 0 ? (
          <>
            <h3 className="pf-res-subhead">{t("mail.reply.history")}</h3>
            <ul className="pf-mail-list">
              {mail.replies.map((reply) => (
                <li key={reply.id} className="pf-hint">
                  {date(reply.sent_at ?? reply.created_at, "datetime")} ·{" "}
                  {t(`mail.reply.status.${reply.status}`, { defaultValue: reply.status })}
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </Card>
  );
}

function Content({ mail, reload }: { mail: InboundMail; reload: () => void }) {
  const { t, i18n } = useTranslation("letters");
  const { date } = useFormat();
  const refresh = useRefreshMail();
  const subject = mail.subject || t("mail.noSubject");
  return (
    <div className="pf-mail">
      <PageHeader
        title={subject}
        subtitle={mail.from_name ? `${mail.from_name} · ${mail.from_email}` : mail.from_email}
        extra={
          <StatusTag kind="inboundMail" status={mail.status}>
            {t(`mail.status.${mail.status}`)}
          </StatusTag>
        }
      />
      <div className="pf-letters-grid">
        <div className="pf-letters-main">
          <Card size="small" title={<h2 className="pf-letters-title">{t("mail.text")}</h2>}>
            <DefinitionList
              items={[
                { label: t("mail.fields.from"), value: mail.from_email },
                { label: t("mail.fields.to"), value: mail.to.join(", ") || null },
                { label: t("mail.fields.received"), value: date(mail.received_at, "datetime") },
                { label: t("mail.fields.client"), value: mail.client?.name ?? null },
                { label: t("mail.fields.lead"), value: mail.lead?.number ?? null },
                { label: t("mail.fields.inns"), value: mail.inns.join(", ") || null },
              ].filter((item) => item.value !== null)}
            />
            {mail.too_large ? <Alert type="warning" showIcon message={t("mail.tooLarge")} /> : null}
            <pre className="pf-mail-text">{mail.text}</pre>
            {mail.attachments.length > 0 ? (
              <>
                <h3 className="pf-res-subhead">{t("mail.files")}</h3>
                <ul className="pf-res-files" aria-label={t("mail.files")}>
                  {mail.attachments.map((file) => (
                    <li key={file.index}>
                      <a
                        className="pf-focusable pf-res-file"
                        href={getDownloadInboundMailAttachmentUrl(mail.id, file.index)}
                        download
                        aria-label={t("mail.download", { name: file.name })}
                      >
                        {file.name}
                      </a>
                      <span className="pf-hint">{formatFileSize(file.size, i18n.language)}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            {mail.skipped.map((file) => (
              <p key={file.name} className="pf-hint pf-mail-what">
                {t("mail.skipped", {
                  name: file.name,
                  reason: t(`mail.skippedReason.${file.reason}`),
                })}
              </p>
            ))}
          </Card>
          <Reply mail={mail} onSent={reload} />
        </div>
        <aside className="pf-letters-side" aria-label={t("mail.actions.title")}>
          <Card size="small">
            {mail.status === "new" ? (
              <div className="pf-mail-actions">
                <Assist mail={mail} onChange={reload} />
                <Actions mail={mail} onDone={() => void refresh()} />
              </div>
            ) : (
              <>
                <h3 className="pf-res-subhead">{t("mail.result.title")}</h3>
                <Result mail={mail} />
              </>
            )}
          </Card>
        </aside>
      </div>
    </div>
  );
}

/** Карточка письма общего ящика (W18A-P2): текст, вложения, «Подсказать», действия одной кнопкой, ответ в цепочку. */
export function MailView({ id }: { id: number }) {
  const { t } = useTranslation(["letters", "modules"]);
  const query = useGetInboundMail(id);
  useDocumentTitle(query.data?.subject || t("modules:eds.sections.mail"));
  if (query.isPending) {
    return (
      <div className="pf-mail">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }
  if (!query.data) {
    const missing = query.error instanceof ApiError && query.error.status === 404;
    return (
      <EmptyState
        title={t(missing ? "letters:state.notFound.title" : "letters:state.loadError.title")}
        text={t(missing ? "letters:state.notFound.text" : "letters:state.loadError.text")}
        action={<LinkButton to="/eds/mail">{t("modules:eds.sections.mail")}</LinkButton>}
      />
    );
  }
  return <Content mail={query.data} reload={() => void query.refetch()} />;
}
