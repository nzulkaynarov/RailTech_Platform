import { DownOutlined } from "@ant-design/icons";
import { Alert, Button, Dropdown, Input, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";

import type {
  InboundMail,
  InboundMailTypeDefaultAction,
} from "../../../shared/api/generated/model";
import {
  archiveInboundMail,
  completeInboundMail,
  createLeadFromInboundMail,
  handoverInboundMail,
  markInboundMailPriceUploaded,
  moveInboundMailToSuspicious,
  takeInboundMail,
  useListInboundMailHandoverTargets,
} from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { ReleaseButton } from "./ReleaseButton";
import { type MailRun, useMailRun } from "./useMailRun";
import { MAIL_ACTIONS, PRICE_UPLOAD_PATH, listPath, registerFromMailPath } from "./mailModel";

/** Шаги с подтверждением; `handover_price` — «Передать на загрузку прайса» (у сотрудника нет права загрузки). */
type Step =
  | Exclude<InboundMailTypeDefaultAction, "register_incoming" | "reply_template">
  | "handover_price"
  | null;

interface StepProps {
  mail: InboundMail;
  run: MailRun;
  pending: boolean;
  cancel?: (() => void) | undefined;
  done: () => void;
}

function Buttons({
  confirm,
  loading,
  disabled,
  cancel,
  onClick,
}: {
  confirm: string;
  loading: boolean;
  disabled?: boolean;
  cancel?: (() => void) | undefined;
  onClick: () => void;
}) {
  const { t } = useTranslation("letters");
  return (
    <div className="pf-fp-row">
      <Button type="primary" loading={loading} disabled={disabled} onClick={onClick}>
        {confirm}
      </Button>
      {cancel ? <Button onClick={cancel}>{t("mail.actions.cancel")}</Button> : null}
    </div>
  );
}

function LeadStep({ mail, run, pending, cancel, done }: StepProps) {
  const { t } = useTranslation("letters");
  return (
    <div className="pf-mail-actions">
      <Consequence title={t("mail.actions.what")} items={[t("mail.actions.leadWhat")]} />
      <Buttons
        confirm={t("mail.actions.leadConfirm")}
        loading={pending}
        cancel={cancel}
        onClick={() =>
          void run(async () => {
            const out = await createLeadFromInboundMail(mail.id);
            return t(out.created ? "mail.actions.leadDone" : "mail.actions.leadNote", {
              number: out.lead_number,
            });
          }, done)
        }
      />
    </div>
  );
}

function ArchiveStep({ mail, run, pending, cancel, done }: StepProps) {
  const { t } = useTranslation("letters");
  const [reason, setReason] = useState(t("mail.actions.mailingReason"));
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
      <Buttons
        confirm={t("mail.actions.archiveConfirm")}
        loading={pending}
        disabled={reason.trim().length < 3}
        cancel={cancel}
        onClick={() =>
          void run(async () => {
            await archiveInboundMail(mail.id, { reason: reason.trim() });
            return t("mail.actions.archived");
          }, done)
        }
      />
    </div>
  );
}

/** Прайс или КП поставщика: загрузка — существующий экран каталога (CAT-1), письмо закрывает человек, когда загрузил. */
function PriceStep({ mail, run, pending, cancel, done }: StepProps) {
  const { t } = useTranslation("letters");
  return (
    <div className="pf-mail-actions">
      <p className="pf-hint pf-mail-what">{t("mail.actions.priceHow")}</p>
      <div>
        <Button href={PRICE_UPLOAD_PATH} target="_blank" rel="noopener noreferrer">
          {t("mail.actions.priceOpen")}
        </Button>
      </div>
      <Consequence title={t("mail.actions.what")} items={[t("mail.actions.priceWhat")]} />
      <Buttons
        confirm={t("mail.actions.priceConfirm")}
        loading={pending}
        cancel={cancel}
        onClick={() =>
          void run(async () => {
            await markInboundMailPriceUploaded(mail.id);
            return t("mail.actions.priceDone");
          }, done)
        }
      />
    </div>
  );
}

/**
 * Передача письма сотруднику: счёт — тому, кто подтверждает оплату; прайс — тому, кто загружает прайсы и видит цены
 * поставщиков (роль — данные, список даёт CRM по правам ролей).
 */
function HandoverStep({
  mail,
  run,
  pending,
  cancel,
  done,
  purpose,
}: StepProps & { purpose: "payments" | "price" }) {
  const { t } = useTranslation("letters");
  const key = purpose === "price" ? "priceHandover" : "handover";
  const targets = useListInboundMailHandoverTargets({ purpose });
  const items = targets.data?.items ?? [];
  const [chosen, setChosen] = useState<number | null>(null);
  const to = chosen ?? (items.length === 1 ? (items[0]?.id ?? null) : null);
  const name = items.find((item) => item.id === to)?.name ?? "";
  return (
    <div className="pf-mail-actions">
      {targets.isPending ? null : items.length === 0 ? (
        <Alert type="info" showIcon role="status" message={t(`mail.actions.${key}None`)} />
      ) : (
        <>
          <label htmlFor="mail-handover-to">{t("mail.actions.handoverTo")}</label>
          <Select
            id="mail-handover-to"
            value={to}
            placeholder={t("mail.actions.handoverPick")}
            options={items.map((item) => ({ value: item.id, label: item.name }))}
            onChange={setChosen}
          />
          <Consequence title={t("mail.actions.what")} items={[t(`mail.actions.${key}What`)]} />
        </>
      )}
      <Buttons
        confirm={t(`mail.actions.${key}Confirm`)}
        loading={pending}
        disabled={to === null}
        cancel={cancel}
        onClick={() =>
          void run(async () => {
            if (to === null) return "";
            await handoverInboundMail(mail.id, { user_id: to, purpose });
            return t(`mail.actions.${key}Done`, { name });
          }, done)
        }
      />
    </div>
  );
}

function SuspiciousStep({ mail, run, pending, cancel, done }: StepProps) {
  const { t } = useTranslation("letters");
  return (
    <div className="pf-mail-actions">
      <Consequence title={t("mail.actions.what")} items={[t("mail.actions.suspiciousWhat")]} />
      <Buttons
        confirm={t("mail.actions.suspiciousConfirm")}
        loading={pending}
        cancel={cancel}
        onClick={() =>
          void run(async () => {
            await moveInboundMailToSuspicious(mail.id);
            return t("mail.actions.suspiciousDone");
          }, done)
        }
      />
    </div>
  );
}

const STEPS: Record<NonNullable<Step>, (props: StepProps) => React.JSX.Element> = {
  create_lead: LeadStep,
  archive_mailing: ArchiveStep,
  supplier_price: PriceStep,
  to_accountant: (props) => <HandoverStep {...props} purpose="payments" />,
  handover_price: (props) => <HandoverStep {...props} purpose="price" />,
  suspicious: SuspiciousStep,
};

/** «Ответить»: письмо отвечает форма под перепиской; кнопка ведёт к её полю. */
function focusReply(): void {
  const field = document.getElementById("mail-reply-text");
  field?.scrollIntoView({ block: "center" });
  field?.focus();
}

/**
 * «Новое» и «В работе у меня»: взять, разобрать, вернуть. Основная кнопка — действие по умолчанию типа письма
 * (MAIL-TYPES), остальные действия — в меню «Другое действие»; у письма без типа действия рядом, без главной. Любое
 * действие берёт письмо само. Что делает действие, решает код; тип только выбирает кнопку.
 */
export function Working({
  mail,
  mine,
  reload,
}: {
  mail: InboundMail;
  mine: boolean;
  reload: () => void;
}) {
  const { t } = useTranslation("letters");
  const navigate = useNavigate();
  const { run, pending, error } = useMailRun(reload);
  const [step, setStep] = useState<Step>(null);
  const { me } = useAuth();
  // Загружать прайсы может тот, у кого есть право на каталог; остальным — передать на загрузку сотруднику с правом.
  const canLoadPrices = canEdit(me, "erp.stock");
  const primary = mail.type?.default_action ?? null;
  const done = () => void navigate(listPath(false));
  const label = (action: InboundMailTypeDefaultAction) =>
    t(`mail.action.${action === "supplier_price" && !canLoadPrices ? "price_handover" : action}`);
  const start = (action: InboundMailTypeDefaultAction) => {
    if (action === "reply_template") focusReply();
    else if (action === "supplier_price" && !canLoadPrices) setStep("handover_price");
    else if (action !== "register_incoming") setStep(action);
  };
  const button = (action: InboundMailTypeDefaultAction, main: boolean) =>
    action === "register_incoming" ? (
      <LinkButton
        key={action}
        type={main ? "primary" : "default"}
        to={registerFromMailPath(mail.id)}
      >
        {label(action)}
      </LinkButton>
    ) : (
      <Button
        key={action}
        type={main ? "primary" : "default"}
        onClick={() => {
          start(action);
        }}
      >
        {label(action)}
      </Button>
    );
  const others = MAIL_ACTIONS.filter((action) => action !== primary);
  const Open = step ? STEPS[step] : null;
  return (
    <div className="pf-mail-actions">
      <div className="pf-fp-row">
        {!mine ? (
          <Button
            type={primary ? "default" : "primary"}
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
        {primary ? (
          <>
            {button(primary, true)}
            <Dropdown
              trigger={["click"]}
              menu={{
                items: others.map((action) => ({
                  key: action,
                  label: label(action),
                })),
                onClick: ({ key }) => {
                  if (key === "register_incoming") {
                    void navigate(registerFromMailPath(mail.id));
                  } else {
                    start(key as InboundMailTypeDefaultAction);
                  }
                },
              }}
            >
              <Button aria-haspopup="menu">
                {t("mail.action.more")} <DownOutlined aria-hidden />
              </Button>
            </Dropdown>
          </>
        ) : (
          MAIL_ACTIONS.map((action) => button(action, false))
        )}
      </div>
      {primary === "register_incoming" || !primary ? (
        <p className="pf-hint pf-mail-what">{t("mail.actions.registerWhat")}</p>
      ) : null}
      {Open ? (
        <Open
          mail={mail}
          run={run}
          pending={pending}
          done={done}
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

/**
 * Письмо, которое передали этому сотруднику (сотрудник без первой линии, ветка «свои письма»): закрыть его, когда работа
 * сделана. Снабженцу с письмом-прайсом — «Прайс загружен — убрать из очереди» (со ссылкой на загрузку), остальным
 * (бухгалтеру со счётом) — «Готово — убрать из очереди». «Вернуть делопроизводителю» — отдельно.
 */
export function OwnWork({ mail, reload }: { mail: InboundMail; reload: () => void }) {
  const { t } = useTranslation("letters");
  const navigate = useNavigate();
  const { me } = useAuth();
  const { run, pending, error } = useMailRun(reload);
  const priceMail = mail.type?.default_action === "supplier_price" && canEdit(me, "erp.stock");
  const done = () => void navigate(listPath(true));
  return (
    <div className="pf-mail-actions">
      {priceMail ? (
        <PriceStep mail={mail} run={run} pending={pending} done={done} />
      ) : (
        <>
          <Consequence title={t("mail.actions.what")} items={[t("mail.actions.completeWhat")]} />
          <div>
            <Button
              type="primary"
              loading={pending}
              onClick={() =>
                void run(async () => {
                  await completeInboundMail(mail.id);
                  return t("mail.actions.completeDone");
                }, done)
              }
            >
              {t("mail.actions.completeConfirm")}
            </Button>
          </div>
        </>
      )}
      {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
    </div>
  );
}
