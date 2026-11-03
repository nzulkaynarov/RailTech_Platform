import { Alert, Button } from "antd";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import type { InboundMail } from "../../../shared/api/generated/model";
import { takeInboundMail } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { Assist } from "./MailAssist";
import { MailOutcome } from "./MailOutcome";
import { SpamActions } from "./SpamActions";
import { MailTypeBlock } from "./MailTypeBlock";
import { OwnWork, Working } from "./MailWork";
import { canReturn, useRefreshMail } from "./mailModel";
import { ReleaseButton } from "./ReleaseButton";
import { useMailRun } from "./useMailRun";

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
          <>
            <OwnWork mail={mail} reload={changed} />
            <ReleaseButton mail={mail} label={t("mail.releaseOwn")} reload={changed} />
          </>
        ) : (
          <p className="pf-hint pf-mail-what">{t("mail.ownHint")}</p>
        )}
      </Panel>
    );
  }
  const type = <MailTypeBlock mail={mail} reload={reload} />;
  if (mail.status === "spam") {
    return (
      <div className="pf-mail-actions">
        {type}
        <SpamActions mail={mail} onDone={() => void refresh()} />
      </div>
    );
  }
  if (mail.status === "done") {
    return (
      <div className="pf-mail-actions">
        {type}
        <h3 className="pf-res-subhead">{t("mail.result.title")}</h3>
        <Result mail={mail} own={own} reload={changed} />
      </div>
    );
  }
  if (mail.status === "registering") {
    return (
      <div className="pf-mail-actions">
        {type}
        <Panel title={t("mail.actions.title")}>
          <Registering mail={mail} reload={reload} />
        </Panel>
      </div>
    );
  }
  const held = mail.status === "in_work" && !mine;
  return (
    <div className="pf-mail-actions">
      {type}
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
