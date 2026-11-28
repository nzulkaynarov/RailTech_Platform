import { App, Button } from "antd";
import { type ReactNode, useId, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { settingByKey } from "../../admin/settingsRegistry";
import type {
  OnBehalfChannel,
  ProjectCard,
  ProjectContractActionInAction,
  ProjectContractActionsItem,
  ProjectContractSendBlocker,
} from "../../../shared/api/generated/model";
import {
  useActEdsProjectContract,
  useCreateEdsProjectContract,
  useScanEdsProjectContract,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { ActionToggle } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { OnBehalfFields } from "../../../shared/ui/OnBehalf";
import { fileUrl, projectRef } from "./api";
import { useFailedText } from "./errors";
import { FileLinks } from "./FileLinks";
import { ReasonForm } from "./forms";
import { ContractTemplateBlock } from "./ContractTemplateBlock";
import { ContractTermBlock } from "./ContractTermBlock";
import { RemarkBlock } from "./RemarkBlock";
import { SignedMark } from "./SignedMark";
import { contractStateKey } from "./model";
import { SigningButton } from "./SigningButton";
import { useApplyCard } from "./useProjectMutations";

type Action = ProjectContractActionInAction;
const FINAL: ReadonlySet<string> = new Set(["signed", "cancelled"]);

/** Что делает главная кнопка в каждом статусе договора (SPEC-v3 §7.3, вкладка «Договор»); остальное — вторичные действия. */
function primaryOf(
  card: ProjectCard,
  allowed: readonly ProjectContractActionsItem[],
): Action | "attach_scan" | null {
  const contract = card.contract;
  if (!contract) return null;
  // ДП-1: пока замечания контрагента на согласовании, договор двигают ответы ответственных, а не отметка сотрудника
  if (contract.remark) return null;
  const pick = (action: ProjectContractActionsItem) => (allowed.includes(action) ? action : null);
  switch (contract.status) {
    case "project":
      if (contract.sent_to_client) return pick("client_agreed");
      return pick("send_to_client"); // ДОК-10: ERP не отдаёт действие, пока договору по шаблону что-то мешает
    case "client_agreed":
    case "issued_at_operator":
      return pick("mark_signed"); // «Ожидает подписания»: скан или заметка (ДП-1)
    case "rejected":
      return pick("revise");
    default:
      return null;
  }
}

/** Роли виз словами на языке сотрудника: по коду права маршрута, слово сервера — запасное (право без перевода). */
function visaRoles(t: TFunction<"projects">, blocker: ProjectContractSendBlocker): string {
  return blocker.missing
    .map((word, i) => {
      const code = blocker.missing_permissions?.[i]?.split(".").pop() ?? "";
      return code ? t(`contract.blocker.role.${code}`, { defaultValue: word }) : word;
    })
    .join(", ");
}

/**
 * Договор не уходит клиенту, пока не собраны визы (Х-1) или не выполнены правила шаблона (ДОК-10): одна проверка ERP. Действие «На согласование клиенту» ERP не предлагает
 * (`actions`), а здесь — причина словами и, если некому визировать, путь без тупика: ссылка в «Сотрудники» тому, у кого
 * есть доступ, остальным — кого попросить.
 */
function SendBlocker({ blocker }: { blocker: ProjectContractSendBlocker }) {
  const { t } = useTranslation("projects");
  const { me } = useAuth();
  const roles = visaRoles(t, blocker);
  const org = settingByKey("org");
  const canOpenSettings = org !== undefined && canSee(me, org.access);
  // Запрос открыт, а кто поставил визы, ещё не пришло: слов о ролях нет — «Визы собираются»
  const key =
    blocker.code === "visas_pending" && blocker.missing.length === 0 ? "collecting" : blocker.code;
  // Правила шаблона (ДОК-10) — свои слова; визы (Х-1) — по коду причины. Проверка на сервере одна.
  const text = blocker.code.startsWith("CONTRACT_")
    ? t(`contract.template.blocker.${blocker.code}`)
    : t(`contract.blocker.${key}`, { roles });
  return (
    <div className="pf-hint" role="status" data-testid="contract-send-blocker">
      <p style={{ margin: 0 }}>{text}</p>
      {blocker.remark ? (
        <p style={{ margin: 0 }}>{t("contract.blocker.remark", { text: blocker.remark })}</p>
      ) : null}
      {blocker.settings_link ? (
        canOpenSettings ? (
          <LinkButton size="small" to="/admin/org">
            {t("contract.blocker.settings")}
          </LinkButton>
        ) : (
          <p style={{ margin: 0 }}>{t("contract.blocker.askAdmin", { roles })}</p>
        )
      ) : null}
    </div>
  );
}

function ContractBody({
  card,
  objectId,
  variant,
  onDone,
}: {
  card: ProjectCard;
  objectId: string;
  variant: "panel" | "sheet";
  onDone?: (() => void) | undefined;
}) {
  const { t } = useTranslation("projects");
  const failedText = useFailedText();
  const { date } = useFormat();
  const { message } = App.useApp();
  const apply = useApplyCard(objectId);
  const ref = projectRef(objectId);
  const contract = card.contract;
  // A2: «Согласован клиентом» — как клиент сообщил и кто со стороны клиента (обязательно).
  const agreedIds = { channel: useId(), person: useId() };
  const [channel, setChannel] = useState<OnBehalfChannel | null>(null);
  const [person, setPerson] = useState("");
  const [agreedTouched, setAgreedTouched] = useState(false);
  // Какое действие сейчас выполняется: кнопка следующего шага, появившаяся с новой карточкой, не должна вертеться.
  const [pending, setPending] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fail = (e: unknown) => {
    setPending(null);
    failedText(e, setError);
  };
  const done = (next: ProjectCard, key: string) => {
    setPending(null);
    setError(null);
    setChannel(null);
    setPerson("");
    setAgreedTouched(false);
    setRejecting(false);
    apply(next);
    void message.success(t(`contract.done.${key}`));
    onDone?.();
  };
  const act = useActEdsProjectContract({ mutation: { onError: fail } });
  const scan = useScanEdsProjectContract({ mutation: { onError: fail } });
  const create = useCreateEdsProjectContract({ mutation: { onError: fail } });
  const busy = act.isPending || scan.isPending || create.isPending;

  // Договора ещё нет: кнопка «Сформировать проект» живёт в строке документа (`ContractCreateButton`).
  if (!contract) return null;

  const allowed = contract.actions;
  const primary = primaryOf(card, allowed);
  const may = (action: ProjectContractActionsItem) => allowed.includes(action);
  const send = (
    action: Action,
    extra: {
      reason?: string;
      note?: string;
      channel?: OnBehalfChannel;
      counterparty_person?: string;
      text?: string;
      approve?: boolean;
      agreement_number?: string;
    } = {},
  ) => {
    setError(null);
    setPending(action);
    act.mutate(
      { ref, data: { action, ...extra } },
      {
        onSuccess: (next) => {
          done(next, action);
        },
      },
    );
  };
  let primaryBlock: ReactNode = null;
  if (primary === "mark_signed") {
    primaryBlock = (
      <SignedMark
        busy={busy}
        error={error}
        onScan={(file) => {
          setError(null);
          scan.mutate(
            { ref, data: { file } },
            {
              onSuccess: (next) => {
                done(next, "attach_scan");
              },
            },
          );
        }}
        onNote={(text) => {
          send("mark_signed", { note: text });
        }}
      />
    );
  } else if (primary !== null) {
    primaryBlock = (
      <form
        key={primary}
        className="pf-fp-form"
        aria-label={t(`contract.action.${primary}`)}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (busy) return;
          if (primary === "client_agreed") {
            setAgreedTouched(true);
            if (!channel || !person.trim()) return;
            send(primary, { channel, counterparty_person: person.trim() });
            return;
          }
          if (primary !== "attach_scan") send(primary, {});
        }}
      >
        {primary === "client_agreed" ? (
          <OnBehalfFields
            ids={agreedIds}
            channel={channel}
            person={person}
            touched={agreedTouched}
            onChannel={setChannel}
            onPerson={setPerson}
          />
        ) : null}
        {error && !rejecting ? (
          <p className="pf-field-error" role="alert">
            {error}
          </p>
        ) : null}
        <Button
          type="primary"
          htmlType="submit"
          block
          loading={pending === primary && !rejecting}
          disabled={busy}
        >
          {t(`contract.action.${primary}`)}
        </Button>
      </form>
    );
  }

  // «На подпись» не предлагается, пока по текущей редакции запрос открыт (визы собираются): повтор — `ALREADY_REQUESTED`
  const requestOpen = !contract.sent_to_client && contract.send_blocker?.code === "visas_pending";
  const canReject = may("reject");
  const stateKey = contractStateKey(contract);
  return (
    <div className={`pf-dec-panel pf-dec--${variant}`}>
      <section
        className="pf-dec-brief"
        aria-label={t("contract.number", { number: contract.number })}
      >
        <p className="pf-dec-note" style={{ margin: 0 }}>
          {t(`contract.state.${stateKey}`)}
        </p>
        <DefinitionList
          items={[
            {
              label: t("contract.fields.total"),
              value: contract.total ? (
                <MoneyText value={contract.total.amount} currency={contract.total.currency} />
              ) : null,
            },
            { label: t("contract.fields.created"), value: date(contract.created_at) },
            {
              label: t("contract.fields.agreed"),
              value: contract.client_agreed_at ? date(contract.client_agreed_at, "datetime") : null,
            },
            {
              label: t("contract.fields.signed"),
              value: contract.signed_at ? date(contract.signed_at, "datetime") : null,
            },
          ]}
        />
        <FileLinks
          items={[
            contract.has_pdf
              ? {
                  url: fileUrl(objectId, "contract", contract.id, "pdf"),
                  label: t("contract.files.pdf"),
                  name: `${contract.number}.pdf`,
                }
              : null,
            contract.sent_to_client && !FINAL.has(contract.status)
              ? {
                  url: fileUrl(objectId, "contract", contract.id, "docx"),
                  label: t("contract.files.docx"),
                  name: `${contract.number}.docx`,
                }
              : null,
            contract.has_scan
              ? {
                  url: fileUrl(objectId, "contract", contract.id, "scan"),
                  label: t("contract.files.scan"),
                  name: `${contract.number}-scan`,
                }
              : null,
          ]}
        />
      </section>

      {contract.template ? (
        <ContractTemplateBlock
          template={contract.template}
          busy={busy}
          pending={pending}
          send={send}
        />
      ) : null}
      {contract.term ? (
        <ContractTermBlock term={contract.term} busy={busy} pending={pending} send={send} />
      ) : null}
      {contract.send_blocker && !contract.sent_to_client ? (
        <SendBlocker blocker={contract.send_blocker} />
      ) : null}
      {contract.remark ? (
        <RemarkBlock
          remark={contract.remark}
          busy={busy}
          pending={pending}
          error={error && !rejecting ? error : null}
          send={(action, extra) => {
            send(action, extra);
          }}
          fileHref={
            contract.remark.has_file ? (
              <FileLinks
                items={[
                  {
                    url: fileUrl(objectId, "contract", contract.id, "remark"),
                    label: t("contract.files.remark", { name: contract.remark.file_name }),
                    name: contract.remark.file_name || `${contract.number}-remark`,
                  },
                ]}
              />
            ) : null
          }
        />
      ) : null}
      {primaryBlock}

      {canReject ? (
        <ActionToggle
          label={t("contract.action.reject")}
          open={rejecting}
          danger
          disabled={busy}
          onToggle={setRejecting}
        >
          <ReasonForm
            labels={{
              title: t("contract.reject.title"),
              label: t("contract.reject.reason.label"),
              hint: t("contract.reject.reason.hint"),
              submit: t("contract.reject.submit"),
              cancel: t("contract.reject.cancel"),
              disabled: t("contract.reject.disabled"),
            }}
            busy={act.isPending}
            error={rejecting ? error : null}
            onSubmit={(reason) => {
              send("reject", { reason });
            }}
            onCancel={() => {
              setRejecting(false);
              setError(null);
            }}
          />
        </ActionToggle>
      ) : null}

      {/* План 0.7 (FR-30): подписанный, отклонённый или отменённый договор на подпись не отправляют */}
      {contract.status !== "signed" &&
      contract.status !== "rejected" &&
      contract.status !== "cancelled" &&
      !requestOpen ? (
        <SigningButton objectId={objectId} kind="contract" documentId={contract.id} />
      ) : null}
    </div>
  );
}

/** Кнопка строки «Договор»: сформировать проект, пока договора нет (тот же вызов, что был во вкладке окна). */
export function ContractCreateButton({ objectId }: { objectId: string }) {
  const { t } = useTranslation("projects");
  const failedText = useFailedText();
  const { message } = App.useApp();
  const apply = useApplyCard(objectId);
  const [error, setError] = useState<string | null>(null);
  const create = useCreateEdsProjectContract({
    mutation: {
      onError: (e) => {
        failedText(e, setError);
      },
    },
  });
  return (
    <>
      <Button
        size="small"
        type="primary"
        aria-label={t("card.documents.createContractLabel")}
        loading={create.isPending}
        disabled={create.isPending}
        onClick={() => {
          setError(null);
          create.mutate(
            { ref: projectRef(objectId) },
            {
              onSuccess: (next) => {
                apply(next);
                void message.success(t("contract.done.create"));
              },
            },
          );
        }}
      >
        {t("card.documents.createContract")}
      </Button>
      {error ? (
        <p className="pf-field-error" role="alert">
          {error}
        </p>
      ) : null}
    </>
  );
}

/** Действия по договору в строке документа: следующий шаг, скан, отклонение, отправка на подпись. Что можно — решает ERP. */
export function ContractPanel({ card, objectId }: { card: ProjectCard; objectId: string }) {
  return <ContractBody card={card} objectId={objectId} variant="panel" />;
}
