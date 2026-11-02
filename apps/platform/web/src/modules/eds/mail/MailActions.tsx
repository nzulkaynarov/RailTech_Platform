import { Alert, App, Button, Input } from "antd";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { InboundMail, InboundMailAssistAction } from "../../../shared/api/generated/model";
import {
  archiveInboundMail,
  createLeadFromInboundMail,
  releaseInboundMail,
  takeInboundMail,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { Assist } from "./MailAssist";
import { MailOutcome } from "./MailOutcome";
import { SpamActions } from "./SpamActions";
import {
  canReturn,
  inWorkByOther,
  listPath,
  registerFromMailPath,
  useRefreshMail,
} from "./mailModel";

type Step = "lead" | "archive" | null;

function reasonOf(error: unknown): string {
  return error instanceof ApiError ? error.message : String(error);
}

/** Выполнить действие над письмом: успех — сообщение, список и счётчики свежие; ошибка — словами. */
function useMailRun(reload: () => void) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const refresh = useRefreshMail();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (work: () => Promise<string>, after?: () => void): Promise<void> => {
    setPending(true);
    setError(null);
    try {
      void message.success(await work());
      await refresh();
      after?.();
    } catch (failure) {
      setError(t("mail.actions.failed", { reason: reasonOf(failure) }));
      // Письмо тем временем взял коллега: экран показывает, у кого оно, и предлагает «Забрать себе».
      if (inWorkByOther(failure)) reload();
    } finally {
      setPending(false);
    }
  };
  return { run, pending, error, setError };
}

/** «В работе у …»: чужое письмо не трогаем, единственное действие — «Забрать себе» с подтверждением. */
function Held({ mail, reload }: { mail: InboundMail; reload: () => void }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const { run, pending, error } = useMailRun(reload);
  const [asking, setAsking] = useState(false);
  const name = mail.assignee?.name ?? t("mail.bulk.colleague");
  return (
    <div className="pf-mail-actions">
      <p className="pf-mail-what">
        {t("mail.busy.title", {
          name,
          time: mail.assigned_at ? date(mail.assigned_at, "time") : "",
        })}
      </p>
      {asking ? (
        <>
          <Consequence title={t("mail.actions.what")} items={[t("mail.busy.what", { name })]} />
          <div className="pf-fp-row">
            <Button
              type="primary"
              loading={pending}
              onClick={() =>
                void run(
                  async () => {
                    await takeInboundMail(mail.id, { takeover: true });
                    return t("mail.takeDone");
                  },
                  () => {
                    setAsking(false);
                    reload();
                  },
                )
              }
            >
              {t("mail.busy.takeOver")}
            </Button>
            <Button
              onClick={() => {
                setAsking(false);
              }}
            >
              {t("mail.actions.cancel")}
            </Button>
          </div>
        </>
      ) : (
        <div>
          <Button
            onClick={() => {
              setAsking(true);
            }}
          >
            {t("mail.busy.takeOver")}
          </Button>
        </div>
      )}
      {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
    </div>
  );
}

function ArchiveStep({
  mail,
  run,
  pending,
  cancel,
}: {
  mail: InboundMail;
  run: ReturnType<typeof useMailRun>["run"];
  pending: boolean;
  cancel: () => void;
}) {
  const { t } = useTranslation("letters");
  const navigate = useNavigate();
  const [reason, setReason] = useState("");
  return (
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
            void run(
              async () => {
                await archiveInboundMail(mail.id, { reason: reason.trim() });
                return t("mail.actions.archived");
              },
              () => void navigate(listPath(false)),
            )
          }
        >
          {t("mail.actions.archiveConfirm")}
        </Button>
        <Button onClick={cancel}>{t("mail.actions.cancel")}</Button>
      </div>
    </div>
  );
}

/** «Новое» и «В работе у меня»: взять, разобрать (ВХ, лид, архив — любое действие берёт письмо само), вернуть. */
function Working({ mail, mine, reload }: { mail: InboundMail; mine: boolean; reload: () => void }) {
  const { t } = useTranslation("letters");
  const navigate = useNavigate();
  const { run, pending, error } = useMailRun(reload);
  const [step, setStep] = useState<Step>(null);
  const suggested: InboundMailAssistAction | null =
    mine && mail.assist.status === "done" ? mail.assist.action : null;
  const kind = (action: InboundMailAssistAction) => (action === suggested ? "primary" : "default");
  const done = () => void navigate(listPath(false));
  return (
    <div className="pf-mail-actions">
      <div className="pf-fp-row">
        {!mine ? (
          <Button
            type="primary"
            loading={pending}
            onClick={() =>
              void run(async () => {
                await takeInboundMail(mail.id, { takeover: false });
                return t("mail.takeDone");
              }, reload)
            }
          >
            {t("mail.take")}
          </Button>
        ) : null}
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
                }, done)
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
        <ArchiveStep
          mail={mail}
          run={run}
          pending={pending}
          cancel={() => {
            setStep(null);
          }}
        />
      ) : null}
      {mine ? <ReleaseButton mail={mail} label={t("mail.release")} reload={reload} /> : null}
      {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
    </div>
  );
}

/** «Вернуть в Новые» (первая линия) или «Вернуть делопроизводителю» (сотрудник со своим письмом). */
function ReleaseButton({
  mail,
  label,
  reload,
}: {
  mail: InboundMail;
  label: string;
  reload: () => void;
}) {
  const { t } = useTranslation("letters");
  const { run, pending, error } = useMailRun(reload);
  return (
    <div className="pf-mail-actions">
      <div>
        <Button
          loading={pending}
          onClick={() =>
            void run(async () => {
              await releaseInboundMail(mail.id);
              return t("mail.returned");
            }, reload)
          }
        >
          {label}
        </Button>
      </div>
      {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
    </div>
  );
}

function Result({ mail, own, reload }: { mail: InboundMail; own: boolean; reload: () => void }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const result = mail.result;
  return (
    <div className="pf-mail-actions">
      <p className="pf-mail-what">
        {result ? <MailOutcome result={result} /> : t("mail.outcome.unknown")}
      </p>
      {result?.by ? (
        <p className="pf-hint pf-mail-what">
          {result.by.name}
          {result.at ? `, ${date(result.at, "datetime")}` : ""}
        </p>
      ) : null}
      {!own && canReturn(mail) ? (
        <ReleaseButton mail={mail} label={t("mail.returnToNew")} reload={reload} />
      ) : null}
    </div>
  );
}

function Registering({ mail, reload }: { mail: InboundMail; reload: () => void }) {
  const { t } = useTranslation("letters");
  return (
    <div className="pf-mail-actions">
      <p className="pf-mail-what">
        {mail.eds_waiting ? t("mail.registeringWaiting") : t("mail.registering")}
      </p>
      <div>
        <Button onClick={reload}>{t("mail.refresh")}</Button>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-labelledby="mail-actions-title" className="pf-mail-actions">
      <h3 id="mail-actions-title" className="pf-res-subhead">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Правая колонка карточки: что можно сделать с письмом в его состоянии (и кому). */
export function MailActions({
  mail,
  own,
  reload,
}: {
  mail: InboundMail;
  own: boolean;
  reload: () => void;
}) {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const refresh = useRefreshMail();
  const mine = mail.assignee !== null && String(mail.assignee.id) === me.id;
  const changed = () => {
    void refresh();
    reload();
  };
  if (own) {
    return (
      <Panel title={t("mail.actions.title")}>
        {mine && mail.status === "in_work" ? (
          <ReleaseButton mail={mail} label={t("mail.releaseOwn")} reload={changed} />
        ) : (
          <p className="pf-hint pf-mail-what">{t("mail.ownHint")}</p>
        )}
      </Panel>
    );
  }
  if (mail.status === "spam") return <SpamActions mail={mail} onDone={() => void refresh()} />;
  if (mail.status === "done") {
    return (
      <>
        <h3 className="pf-res-subhead">{t("mail.result.title")}</h3>
        <Result mail={mail} own={own} reload={changed} />
      </>
    );
  }
  if (mail.status === "registering") {
    return (
      <Panel title={t("mail.actions.title")}>
        <Registering mail={mail} reload={reload} />
      </Panel>
    );
  }
  const held = mail.status === "in_work" && !mine;
  return (
    <div className="pf-mail-actions">
      {held ? null : <Assist mail={mail} onChange={reload} />}
      <Panel title={t("mail.actions.title")}>
        {held ? (
          <Held mail={mail} reload={changed} />
        ) : (
          <Working mail={mail} mine={mine} reload={changed} />
        )}
      </Panel>
    </div>
  );
}
