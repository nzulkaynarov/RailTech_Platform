import { Alert, App, Button, Card, Checkbox, Input, Select, Space } from "antd";
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { LetterDuplicate, LetterResolutionKind } from "../../../shared/api/generated/model";
import {
  decideAiSuggestion,
  registerLetter,
  useListEdsStaff,
  useListLetterKinds,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { DefinitionList, type DefinitionItem } from "../../../shared/ui/DefinitionList";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { useRefreshLetters } from "../inbox/api";
import { signedByAfter } from "./signedBy";
import { useRefreshMail } from "../mail/mailModel";
import { RESOLUTION_KINDS } from "../inbox/officeModel";
import { AttachmentsField } from "../new/AttachmentsField";
import { DealField } from "../new/DealField";
import { CompanyPicker, PersonPicker } from "../../../shared/ui/pickers";
import type { Attachment } from "../new/formModel";
import { todayInCompanyZone } from "../new/formModel";
import { localName, useLetterDictionary, useResolutionKindName } from "../dictionaries";
import {
  REGISTER_ORDER,
  type RegisterErrors,
  type RegisterField,
  type RegisterValues,
  emptyRegister,
  registerFieldId,
  toRegisterBody,
  validateRegister,
} from "./registerModel";
import {
  type RemainingItem,
  StepRemaining,
  StepSections,
} from "../../../shared/ui/StepSections/StepSections";
import { useLeftSteps } from "../../../shared/ui/StepSections/useLeftSteps";
import { AiFillBar } from "./AiFillBar";
import { DuplicateNotice } from "./DuplicateCheck";
import { type ForceState, duplicateFromError, useDuplicateCheck } from "./duplicates";
import {
  type AiField,
  applySuggestion,
  byCodeFields,
  decisionOf,
  revertSuggestion,
} from "./aiFill";
import {
  clearRegisterDraft,
  DRAFT_FILE_KEY,
  readRegisterDraft,
  type RegisterSection,
  writeRegisterDraft,
} from "./draft";
import { useMailPrefill } from "./useMailPrefill";

import "../new/new.css";
import "./register.css";

/** Поля, заполненные «Заполнить из файла» и ещё не исправленные человеком (id поля формы). */
const SuggestedFields = createContext<{ ids: ReadonlySet<string>; byCode: ReadonlySet<string> }>({
  ids: new Set(),
  byCode: new Set(),
});

const AI_FIELD_IDS: Readonly<Record<AiField, string>> = {
  senderName: registerFieldId("sender_name"),
  senderInn: registerFieldId("sender_inn"),
  refNumber: "reg-ref-number",
  refDate: "reg-ref-date",
  subject: registerFieldId("subject"),
  summary: "reg-summary",
  kind: registerFieldId("kind"),
  documentDue: "reg-document-due",
};

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: string | undefined;
  children: ReactNode;
}) {
  const { t } = useTranslation("letters");
  const marks = useContext(SuggestedFields);
  const suggested = marks.ids.has(id);
  return (
    <div className="pf-fp-field">
      <label htmlFor={id}>{label}</label>
      {suggested ? (
        <span className="pf-reg-ai-chip">
          {t(marks.byCode.has(id) ? "register.ai.chipRules" : "register.ai.chip")}
        </span>
      ) : null}
      {children}
      {error ? (
        <span className="pf-field-error" id={`${id}-error`} role="alert">
          {error}
        </span>
      ) : null}
      {hint ? (
        <span className="pf-hint" id={`${id}-hint`}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

function describedBy(id: string, hint: boolean, error: boolean): string | undefined {
  const parts = [error ? `${id}-error` : "", hint ? `${id}-hint` : ""].filter(Boolean);
  return parts.length > 0 ? parts.join(" ") : undefined;
}

function newKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

type SectionKey = RegisterSection;

/** Поле с ошибкой → его секция (форма секциями, platform-frontend.md §4.1a) */
const SECTION_OF: Record<RegisterField, SectionKey> = {
  file_ids: "file",
  kind: "sender",
  receipt_method: "sender",
  sender_name: "sender",
  sender_inn: "sender",
  received_at: "sender",
  subject: "content",
  document_due: "route",
  related_number: "route",
};

/** Поля ошибки сервера (`details.fields`: `body.kind` от BFF, `related_number` от EDS) → поля формы. */
function serverFields(error: unknown): RegisterField[] {
  if (!(error instanceof ApiError)) return [];
  const raw = error.details["fields"];
  if (!Array.isArray(raw)) return [];
  const known = (name: string): name is RegisterField =>
    (REGISTER_ORDER as readonly string[]).includes(name);
  return raw.flatMap((item): RegisterField[] => {
    if (typeof item !== "string") return [];
    const name = item.split(".").filter((part) => part !== "body")[0] ?? "";
    return known(name) ? [name] : [];
  });
}

/**
 * EDS · «Зарегистрировать входящее» (P8, SPEC-v3 §3.2a п. 1): карточка делопроизводства для бумажных писем, требований
 * налоговой из my.soliq, писем банка и поставщиков. Результат — номер ВХ, статус «Ждёт резолюции» и строка у директора в
 * «Моих задачах». Резолюцию здесь не накладывают: это право директора (раздел `eds.inbox` полный).
 */
export function RegisterLetterPage() {
  const { t, i18n } = useTranslation(["letters", "modules", "documents"]);
  const { me } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { mobile } = useViewport();
  const { date } = useFormat();
  const refresh = useRefreshLetters();
  const today = todayInCompanyZone();
  const [values, setValues] = useState<RegisterValues>(() => emptyRegister(today));
  // Отказ сервера по полям (номер входящего не найден, файл отвергнут): заранее не проверить; снимается правкой формы.
  const [serverErrors, setServerErrors] = useState<RegisterErrors>({});
  const [active, setActive] = useState<SectionKey>("file");
  // Шаги, которые человек уже покидал: требования и ошибки полей видны на них, а не на только что открытом шаге.
  const { left, markLeft } = useLeftSteps(active);
  const [note, setNote] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const idempotency = useRef<{ body: string; key: string } | null>(null);
  // the «Подписал» text a chosen person put in on their own: only such text may be replaced or cleared
  const autoSigned = useRef("");
  // EDS-DUP: фоновая проверка дублей, найденный при отправке ВХ (409) и «Это другое письмо» с причиной.
  const checked = useDuplicateCheck(values);
  // Найденный по 409 ВХ — пока не правили ключевые поля (корреспондент, ИНН, номер, дата): правка — проверка заново.
  const dupFields = [values.senderName, values.senderInn, values.refNumber, values.refDate].join(
    "\u0000",
  );
  const [serverHit, setServerDup] = useState<{ item: LetterDuplicate; fields: string } | null>(
    null,
  );
  const serverDup = serverHit?.fields === dupFields ? serverHit.item : null;
  const duplicates =
    serverDup && !checked.some((item) => item.id === serverDup.id)
      ? [serverDup, ...checked]
      : checked;
  const exactFound = duplicates.some((item) => item.match === "exact");
  const [force, setForce] = useState<ForceState>({ on: false, reason: "" });
  const [reasonError, setReasonError] = useState(false);
  const forcing = force.on && exactFound;
  const [params] = useSearchParams();
  const mailParam = Number(params.get("mail"));
  const mailId = Number.isInteger(mailParam) && mailParam > 0 ? mailParam : null;
  const applyMail = useCallback((update: (prev: RegisterValues) => RegisterValues) => {
    setValues(update);
  }, []);
  const fromMail = useMailPrefill(mailId, applyMail);
  // Черновик (СЦ-10): предлагается, а не подставляется молча; из почты — не предлагается и не пишется.
  const userId = me.id;
  const [offer, setOffer] = useState(() =>
    mailId === null && userId ? readRegisterDraft(userId) : null,
  );
  const [restoredFileId, setRestoredFileId] = useState<string | null>(null);
  const refreshMail = useRefreshMail();
  const kinds = useListLetterKinds({ query: { staleTime: 5 * 60_000 } });
  const methods = useLetterDictionary("receipt-methods");
  const resolutionKindName = useResolutionKindName();
  const staff = useListEdsStaff({ query: { staleTime: 5 * 60_000 } });
  const people = (staff.data?.items ?? []).map((person) => ({
    value: person.id,
    label: person.position ? `${person.name} · ${person.position}` : person.name,
  }));
  const canLink = canSee(me, { anyOf: ["crm.clients", "eds.projects"] });
  const uploading =
    values.attachments.some((a) => a.status === "uploading") ||
    fromMail.state === "loading" ||
    fromMail.state === "busy";
  const title = t("modules:eds.sections.register");
  useDocumentTitle(title);

  // «Заполнить из файла» (EDS-REG): id предложения, заполненные поля и те, что человек ещё не правил.
  // Последние значения формы — для предложения из файла, которое приходит через секунды (ВХ)
  const latest = useRef(values);
  useEffect(() => {
    latest.current = values;
  }, [values]);
  const [ai, setAi] = useState<{
    id: string;
    filled: AiField[];
    left: Set<AiField>;
    byCode: Set<AiField>;
    receivedUsed: string;
  } | null>(null);
  useEffect(() => {
    // Пока на плашке не выбрано «Продолжить» или «Начать заново», прежний черновик не трогаем.
    if (!userId || mailId !== null || offer) return;
    writeRegisterDraft(userId, today, {
      values,
      active,
      ai: ai
        ? {
            id: ai.id,
            filled: ai.filled,
            left: [...ai.left],
            byCode: [...ai.byCode],
            receivedUsed: ai.receivedUsed,
          }
        : null,
    });
  }, [userId, mailId, offer, values, active, ai, today]);
  const touch = (key: keyof RegisterValues) => {
    setAi((prev) => {
      if (!prev?.left.has(key as AiField)) return prev;
      const left = new Set(prev.left);
      left.delete(key as AiField);
      return { ...prev, left };
    });
  };
  const set = <K extends keyof RegisterValues>(key: K, value: RegisterValues[K]) => {
    setServerErrors({});
    setValues((prev) => ({ ...prev, [key]: value }));
    touch(key);
  };
  const report = (decision: "accepted" | "edited" | "manual") => {
    if (ai) void decideAiSuggestion(ai.id, { decision }).catch(() => undefined);
  };
  const setAttachments = (updater: (prev: Attachment[]) => Attachment[]) => {
    setServerErrors({});
    setValues((prev) => ({ ...prev, attachments: updater(prev.attachments) }));
  };
  // Один валидатор на всё: галочка шага, «Осталось» и отправка. Ошибка у поля видна, когда шаг уже покидали.
  const chosenKind = kinds.data?.items.find((item) => item.code === values.kind);
  const dueRequired = chosenKind?.due_required === true;
  const all = validateRegister(values, today, dueRequired);
  const errors: RegisterErrors = {
    ...Object.fromEntries(
      REGISTER_ORDER.filter((field) => all[field] && left.has(SECTION_OF[field])).map((field) => [
        field,
        true,
      ]),
    ),
    ...serverErrors,
  };
  const serverInvalid = (key: SectionKey) =>
    (Object.keys(serverErrors) as RegisterField[]).some((field) => SECTION_OF[field] === key);
  const needs = (key: SectionKey): string[] => [
    ...REGISTER_ORDER.filter((field) => all[field] && SECTION_OF[field] === key).map((field) =>
      t(`letters:register.errors.${field}`),
    ),
    ...(key === "file" && uploading ? [t("documents:form.validation.uploading")] : []),
  ];
  const stepTitles: Record<SectionKey, string> = {
    file: t("letters:register.sections.file"),
    sender: t("letters:register.sections.sender"),
    content: t("letters:register.sections.content"),
    route: t("letters:register.sections.route"),
    review: t("letters:register.sections.review"),
  };
  // Порядок шагов; сводку входящего на «Проверке» добавляет СЦ-11, здесь только «Осталось»
  const remaining: RemainingItem[] = (["file", "sender", "content", "route"] as const).flatMap(
    (key) => needs(key).map((text) => ({ step: key, title: stepTitles[key], text })),
  );
  const doneFiles = values.attachments.filter((a) => a.status === "done");
  // Сводка «Проверки» (СЦ-11): что будет записано в реестр. Пустое необязательное не показываем; поля сделки и клиента — только
  // когда письмо связано со сделкой.
  const methodName = methods.data?.items.find((item) => item.code === values.receiptMethod);
  const addresseeName = people.find((person) => person.value === values.addresseeId)?.label;
  const summaryItems: DefinitionItem[] = [
    {
      label: t("letters:register.kind.label"),
      value: chosenKind ? localName(chosenKind.name, i18n.language) : null,
    },
    {
      label: t("letters:register.method.label"),
      value: methodName ? localName(methodName.name, i18n.language) : null,
    },
    {
      label: t("letters:register.sender.label"),
      value: [values.senderName.trim(), values.senderInn.trim()].filter(Boolean).join(" · "),
    },
    {
      label: t("letters:register.review.ref"),
      value: [values.refNumber.trim(), values.refDate ? date(values.refDate) : ""]
        .filter(Boolean)
        .join(" · "),
    },
    {
      label: t("letters:register.receivedAt.label"),
      value: values.receivedAt ? date(values.receivedAt) : null,
    },
    { label: t("letters:register.subject.label"), value: values.subject.trim() },
    {
      label: t("letters:register.documentDue.label"),
      value: values.documentDue ? date(values.documentDue) : null,
    },
    {
      label: t("letters:register.addressee.label"),
      value: addresseeName ?? t("letters:register.addressee.default"),
    },
    ...(values.urgent
      ? [{ label: t("letters:register.urgent"), value: t("letters:register.review.yes") }]
      : []),
    ...(values.deal ? [{ label: t("letters:register.deal.label"), value: values.deal.label }] : []),
    ...(values.relatedNumber.trim()
      ? [{ label: t("letters:register.related.label"), value: values.relatedNumber.trim() }]
      : []),
    ...(values.draftKind
      ? [{ label: t("letters:register.review.draft"), value: resolutionKindName(values.draftKind) }]
      : []),
    { label: t("letters:register.review.files"), value: doneFiles.map((a) => a.name).join(", ") },
  ].filter((item) => item.value !== null && item.value !== "");
  const fileSummary = [
    doneFiles.map((a) => a.name).join(", "),
    ai ? t("letters:register.ai.applied", { count: ai.left.size }) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const fieldError = (field: RegisterField) =>
    errors[field] ? t(`letters:register.errors.${field}`) : undefined;
  const focus = (field: RegisterField) => {
    // Ошибка открывает свою секцию (platform-frontend.md §4.1a), фокус — после отрисовки
    setActive(SECTION_OF[field]);
    window.setTimeout(() => {
      document.getElementById(registerFieldId(field))?.focus();
    }, 0);
  };

  const submit = async () => {
    setNote(null);
    // Главная кнопка при незаполненном недоступна; сюда доходит Enter в поле — на «Проверку» со списком «Осталось»
    if (remaining.length > 0) {
      setActive("review");
      return;
    }
    if (forcing && !force.reason.trim()) {
      setReasonError(true);
      window.setTimeout(() => document.getElementById("reg-force-reason")?.focus(), 0);
      return;
    }
    setReasonError(false);
    const body = {
      ...toRegisterBody(values),
      ...(forcing ? { force: true, force_reason: force.reason.trim() } : {}),
    };
    const json = JSON.stringify(body);
    if (idempotency.current?.body !== json) idempotency.current = { body: json, key: newKey() };
    setPending(true);
    try {
      const card = await registerLetter(body, {
        headers: { "Idempotency-Key": idempotency.current.key },
      });
      clearRegisterDraft(userId);
      void refresh();
      if (ai) report(decisionOf(ai.filled, ai.left));
      if (values.sourceMailId !== null) void refreshMail();
      void message.success(t("letters:register.toast", { number: card.number }));
      const search = new URLSearchParams({ letter: card.number, tab: "resolution" });
      if (mobile) search.set("sheet", "resolution");
      else search.set("panel", "open");
      void navigate({ pathname: "/eds/inbox", search: `?${search.toString()}` });
    } catch (error) {
      const found = duplicateFromError(error);
      if (found) {
        // То же письмо уже есть (EDS-DUP): показать его рядом с номером, ВХ не создан.
        setServerDup({ item: { ...found, match: "exact" }, fields: dupFields });
        setNote(t("letters:register.duplicate.blocked", { number: found.number }));
        window.setTimeout(() => {
          // фокус на «Открыть» найденного ВХ: блок прокручивается в вид и читается экранным диктором
          document
            .getElementById("reg-duplicates")
            ?.querySelector<HTMLElement>("a, button")
            ?.focus();
        }, 0);
        return;
      }
      const fields = serverFields(error);
      // Файл из черновика уже не приложить (СЦ-10): убираем восстановленные, просим загрузить заново.
      if (fields.includes("file_ids")) {
        setAttachments((prev) => prev.filter((file) => !file.key.startsWith(DRAFT_FILE_KEY)));
      }
      setServerErrors(Object.fromEntries(fields.map((field) => [field, true])));
      markLeft(fields.map((field) => SECTION_OF[field]));
      const reason =
        error instanceof ApiError && error.status === 403
          ? t("letters:register.errors.forbidden")
          : fields[0]
            ? t(`letters:register.errors.${fields[0]}`)
            : t("letters:register.errors.server");
      setNote(t("letters:register.notRegistered", { reason }));
      if (fields[0]) focus(fields[0]);
    } finally {
      setPending(false);
    }
  };

  const id = registerFieldId;
  const kindOptions = (kinds.data?.items ?? []).map((kind) => ({
    value: kind.code,
    label: localName(kind.name, i18n.language),
  }));

  return (
    <div className="pf-newdoc">
      <PageHeader title={title} />
      {fromMail.state === "busy" && fromMail.holder ? (
        <Alert
          type="warning"
          showIcon
          role="alert"
          message={t("letters:mail.busy.title", {
            name: fromMail.holder.name,
            time: fromMail.holder.since ? date(fromMail.holder.since, "time") : "",
          })}
          description={
            <div className="pf-mail-actions">
              <div>
                <Button onClick={fromMail.takeOver}>{t("letters:mail.busy.takeOver")}</Button>
              </div>
            </div>
          }
        />
      ) : fromMail.state !== "idle" ? (
        <Alert
          type={
            fromMail.state === "files_failed" || fromMail.state === "failed" ? "warning" : "info"
          }
          showIcon
          role="status"
          message={
            fromMail.state === "loading"
              ? t("letters:mail.fromMailLoading")
              : fromMail.state === "failed"
                ? t("letters:state.loadError.title")
                : t("letters:mail.fromMail", {
                    subject: fromMail.subject,
                    sender: fromMail.sender,
                  })
          }
          description={
            fromMail.state === "files_failed" ? t("letters:mail.fromMailFailed") : undefined
          }
        />
      ) : null}
      {offer ? (
        <Alert
          type="info"
          showIcon
          role="status"
          message={t("letters:register.saved.found", {
            time: date(offer.savedAt, "datetime"),
            files: offer.values.attachments.map((file) => file.name).join(", "),
          })}
          description={
            <Space wrap>
              <Button
                type="primary"
                size="small"
                onClick={() => {
                  setValues({ ...offer.values, sourceMailId: null });
                  setAi(
                    offer.ai
                      ? {
                          id: offer.ai.id,
                          filled: offer.ai.filled,
                          left: new Set(offer.ai.left),
                          byCode: new Set(offer.ai.byCode ?? []),
                          receivedUsed: offer.ai.receivedUsed ?? "",
                        }
                      : null,
                  );
                  markLeft(
                    (["file", "sender", "content", "route", "review"] as const).slice(
                      0,
                      ["file", "sender", "content", "route", "review"].indexOf(offer.active),
                    ),
                  );
                  setActive(offer.active);
                  setRestoredFileId(
                    offer.values.attachments.find((file) => file.status === "done" && file.id)
                      ?.id ?? null,
                  );
                  setOffer(null);
                }}
              >
                {t("letters:register.saved.continue")}
              </Button>
              <Button
                size="small"
                onClick={() => {
                  clearRegisterDraft(userId);
                  setOffer(null);
                }}
              >
                {t("letters:register.saved.restart")}
              </Button>
            </Space>
          }
        />
      ) : null}
      <SuggestedFields.Provider
        value={{
          ids: new Set(ai ? [...ai.left].map((key) => AI_FIELD_IDS[key]) : []),
          byCode: new Set([...(ai?.byCode ?? [])].map((key) => AI_FIELD_IDS[key])),
        }}
      >
        <form
          aria-label={t("letters:register.formLabel")}
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!pending) void submit();
          }}
        >
          <Card>
            {/* Дубль виден при любой открытой секции: человек решает до регистрации (EDS-DUP) */}
            <DuplicateNotice
              items={duplicates}
              force={force}
              onForce={(next) => {
                setForce(next);
                if (next.reason.trim()) setReasonError(false);
              }}
              reasonError={reasonError}
            />
            <StepSections
              active={active}
              onActiveChange={(key) => {
                setActive(key as SectionKey);
              }}
              sections={[
                {
                  key: "file",
                  title: t("letters:register.sections.file"),
                  summary: fileSummary,
                  complete: true,
                  requirements: needs("file"),
                  showRequirements: left.has("file"),
                  invalid: serverInvalid("file"),
                  content: (
                    <div className="pf-fp-form">
                      <Field
                        id={id("file_ids")}
                        label={t("letters:register.files.label")}
                        hint={t("letters:register.files.hint")}
                        error={fieldError("file_ids")}
                      >
                        <AttachmentsField
                          id={id("file_ids")}
                          value={values.attachments}
                          onChange={setAttachments}
                        />
                      </Field>
                      <AiFillBar
                        noAutoFor={restoredFileId}
                        attachments={values.attachments}
                        applied={ai?.left.size ?? 0}
                        rules={
                          ai !== null &&
                          ai.left.size > 0 &&
                          [...ai.left].every((k) => ai.byCode.has(k))
                        }
                        staleDue={
                          ai !== null &&
                          ai.left.has("documentDue") &&
                          ai.byCode.has("documentDue") &&
                          ai.receivedUsed !== values.receivedAt
                        }
                        onRecompute={(due, used) => {
                          setValues((prev) => ({ ...prev, documentDue: due }));
                          setAi((prev) => (prev ? { ...prev, receivedUsed: used } : prev));
                        }}
                        receivedAt={values.receivedAt}
                        today={today}
                        linkQuery={
                          canLink && !values.deal && ai
                            ? { inn: values.senderInn.trim(), name: values.senderName.trim() }
                            : null
                        }
                        onSuggestion={(suggestion) => {
                          // Распознавание идёт секунды: человек мог уже ввести поля — они главнее, заполняются только пустые.
                          const result = applySuggestion(
                            latest.current,
                            suggestion.fields,
                            kinds.data?.items ?? [],
                          );
                          setValues(result.values);
                          setAi({
                            id: suggestion.suggestion_id,
                            filled: result.filled,
                            left: new Set(result.filled),
                            byCode: new Set(
                              byCodeFields(suggestion).filter((k) => result.filled.includes(k)),
                            ),
                            receivedUsed: latest.current.receivedAt,
                          });
                        }}
                        onRevert={() => {
                          if (!ai) return;
                          setValues((prev) => revertSuggestion(prev, [...ai.left]));
                          report("manual");
                          setAi(null);
                        }}
                        onLinkDeal={(choice) => {
                          set("deal", choice);
                        }}
                      />
                    </div>
                  ),
                },
                {
                  key: "sender",
                  title: t("letters:register.sections.sender"),
                  summary: [values.senderName.trim(), values.refNumber.trim()]
                    .filter(Boolean)
                    .join(" · "),
                  complete: true,
                  requirements: needs("sender"),
                  showRequirements: left.has("sender"),
                  invalid: serverInvalid("sender"),
                  content: (
                    <div className="pf-fp-form">
                      <div className="pf-newdoc-row">
                        <Field
                          id={id("kind")}
                          label={t("letters:register.kind.label")}
                          hint={kinds.isError ? t("letters:register.kind.unavailable") : undefined}
                          error={fieldError("kind")}
                        >
                          <Select
                            id={id("kind")}
                            value={values.kind || undefined}
                            placeholder={t("letters:register.choose")}
                            loading={kinds.isPending}
                            options={kindOptions}
                            status={errors.kind ? "error" : undefined}
                            aria-invalid={errors.kind || undefined}
                            aria-describedby={describedBy(
                              id("kind"),
                              kinds.isError,
                              Boolean(errors.kind),
                            )}
                            onChange={(code: string) => {
                              touch("kind");
                              const kind = kinds.data?.items.find((item) => item.code === code);
                              setValues((prev) => ({
                                ...prev,
                                kind: code,
                                // Требование ГНК сразу «срочно» (SPEC-v3 §3.2a п. 1); снять галочку можно, EDS всё равно поставит.
                                urgent: kind?.urgent ? true : prev.urgent,
                                receiptMethod:
                                  kind?.code === "tax_notice" && !prev.receiptMethod
                                    ? "taxpayer_cabinet"
                                    : prev.receiptMethod,
                              }));
                            }}
                          />
                        </Field>
                        <Field
                          id={id("receipt_method")}
                          label={t("letters:register.method.label")}
                          hint={
                            methods.isError ? t("letters:register.method.unavailable") : undefined
                          }
                          error={fieldError("receipt_method")}
                        >
                          <Select
                            id={id("receipt_method")}
                            value={values.receiptMethod || undefined}
                            placeholder={t("letters:register.choose")}
                            loading={methods.isPending}
                            options={(methods.data?.items ?? []).map((item) => ({
                              value: item.code,
                              label: localName(item.name, i18n.language),
                            }))}
                            status={errors.receipt_method ? "error" : undefined}
                            aria-invalid={errors.receipt_method || undefined}
                            aria-describedby={describedBy(
                              id("receipt_method"),
                              methods.isError,
                              Boolean(errors.receipt_method),
                            )}
                            onChange={(value) => {
                              set("receiptMethod", value);
                            }}
                          />
                        </Field>
                      </div>
                      <div className="pf-newdoc-row">
                        <Field
                          id={id("sender_name")}
                          label={t("letters:register.sender.label")}
                          hint={
                            values.senderCompanyId && values.senderInn
                              ? t("documents:form.recipient.innShort", { inn: values.senderInn })
                              : values.senderCompanyId
                                ? undefined
                                : t("letters:register.sender.hint")
                          }
                          error={fieldError("sender_name")}
                        >
                          {/* ЕД-6: корреспондент — только выбором из контрагентов */}
                          <CompanyPicker
                            id={id("sender_name")}
                            value={
                              values.senderCompanyId
                                ? {
                                    id: values.senderCompanyId,
                                    name: values.senderName,
                                    inn: values.senderInn || null,
                                  }
                                : null
                            }
                            suggest={values.senderCompanyId ? undefined : values.senderName}
                            invalid={Boolean(errors.sender_name)}
                            describedBy={describedBy(
                              id("sender_name"),
                              true,
                              Boolean(errors.sender_name),
                            )}
                            onChange={(company) => {
                              const auto = autoSigned.current;
                              autoSigned.current = "";
                              setValues((prev) => ({
                                ...prev,
                                senderName: company?.name ?? "",
                                senderInn: company?.inn ?? "",
                                senderCompanyId: company?.id ?? "",
                                senderContactId: "",
                                signedBy: signedByAfter(prev.signedBy, auto, null),
                              }));
                            }}
                          />
                        </Field>
                        <Field
                          id="reg-sender-person"
                          label={t("letters:register.person.label")}
                          hint={t("letters:register.person.hint")}
                        >
                          <PersonPicker
                            id="reg-sender-person"
                            companyId={values.senderCompanyId}
                            value={values.senderContactId}
                            describedBy="reg-sender-person-hint"
                            onChange={(person) => {
                              const auto = autoSigned.current;
                              const name = person?.name ?? null;
                              autoSigned.current =
                                name !== null && signedByAfter(values.signedBy, auto, name) === name
                                  ? name
                                  : "";
                              setValues((prev) => ({
                                ...prev,
                                senderContactId: person?.id ?? "",
                                signedBy: signedByAfter(prev.signedBy, auto, person?.name ?? null),
                              }));
                            }}
                          />
                        </Field>
                      </div>
                      <div className="pf-newdoc-row">
                        <Field id="reg-ref-number" label={t("letters:register.refNumber.label")}>
                          <Input
                            id="reg-ref-number"
                            value={values.refNumber}
                            maxLength={64}
                            autoComplete="off"
                            onChange={(event) => {
                              set("refNumber", event.target.value);
                            }}
                          />
                        </Field>
                        <Field id="reg-ref-date" label={t("letters:register.refDate.label")}>
                          <DateField
                            id="reg-ref-date"
                            value={values.refDate}
                            onChange={(next) => {
                              set("refDate", next);
                            }}
                          />
                        </Field>
                      </div>
                      <div className="pf-newdoc-row">
                        <Field id="reg-signed-by" label={t("letters:register.signedBy.label")}>
                          <Input
                            id="reg-signed-by"
                            value={values.signedBy}
                            maxLength={255}
                            autoComplete="off"
                            onChange={(event) => {
                              set("signedBy", event.target.value);
                            }}
                          />
                        </Field>
                        <Field
                          id={id("received_at")}
                          label={t("letters:register.receivedAt.label")}
                          error={fieldError("received_at")}
                        >
                          <DateField
                            id={id("received_at")}
                            value={values.receivedAt}
                            status={errors.received_at ? "error" : undefined}
                            aria-invalid={errors.received_at || undefined}
                            aria-describedby={describedBy(
                              id("received_at"),
                              false,
                              Boolean(errors.received_at),
                            )}
                            onChange={(next) => {
                              set("receivedAt", next);
                            }}
                          />
                        </Field>
                      </div>
                    </div>
                  ),
                },
                {
                  key: "content",
                  title: t("letters:register.sections.content"),
                  summary: values.subject.trim(),
                  complete: true,
                  requirements: needs("content"),
                  showRequirements: left.has("content"),
                  invalid: serverInvalid("content"),
                  content: (
                    <div className="pf-fp-form">
                      <Field
                        id={id("subject")}
                        label={t("letters:register.subject.label")}
                        error={fieldError("subject")}
                      >
                        <Input
                          id={id("subject")}
                          value={values.subject}
                          maxLength={300}
                          autoComplete="off"
                          status={errors.subject ? "error" : undefined}
                          aria-invalid={errors.subject || undefined}
                          aria-describedby={describedBy(
                            id("subject"),
                            false,
                            Boolean(errors.subject),
                          )}
                          onChange={(event) => {
                            set("subject", event.target.value);
                          }}
                        />
                      </Field>
                      <Field
                        id="reg-summary"
                        label={t("letters:register.summary.label")}
                        hint={t("letters:register.summary.hint")}
                      >
                        <Input.TextArea
                          id="reg-summary"
                          rows={4}
                          maxLength={10000}
                          value={values.summary}
                          aria-describedby="reg-summary-hint"
                          onChange={(event) => {
                            set("summary", event.target.value);
                          }}
                        />
                      </Field>
                    </div>
                  ),
                },
                {
                  key: "route",
                  title: t("letters:register.sections.route"),
                  // Обязательных полей нет: галочка — когда шаг пройден, а не раньше человека
                  complete: left.has("route"),
                  requirements: needs("route"),
                  showRequirements: left.has("route"),
                  invalid: serverInvalid("route"),
                  content: (
                    <div className="pf-fp-form">
                      <div className="pf-newdoc-row">
                        <Field
                          id="reg-document-due"
                          label={t("letters:register.documentDue.label")}
                          hint={
                            dueRequired
                              ? `${t("letters:register.documentDue.required")}. ${t("letters:register.documentDue.hint")}`
                              : t("letters:register.documentDue.hint")
                          }
                          error={fieldError("document_due")}
                        >
                          <DateField
                            id="reg-document-due"
                            value={values.documentDue}
                            status={errors.document_due ? "error" : undefined}
                            aria-required={dueRequired || undefined}
                            aria-invalid={errors.document_due || undefined}
                            aria-describedby={describedBy(
                              "reg-document-due",
                              true,
                              Boolean(errors.document_due),
                            )}
                            onChange={(next) => {
                              set("documentDue", next);
                            }}
                          />
                        </Field>
                        <Field
                          id="reg-addressee"
                          label={t("letters:register.addressee.label")}
                          hint={t("letters:register.addressee.hint")}
                        >
                          {/* P8b: адресат — любой активный сотрудник; пусто — директор (его назначает EDS) */}
                          <Select
                            id="reg-addressee"
                            value={values.addresseeId || undefined}
                            placeholder={t("letters:register.addressee.default")}
                            allowClear
                            showSearch
                            optionFilterProp="label"
                            loading={staff.isPending}
                            options={people}
                            aria-describedby="reg-addressee-hint"
                            onChange={(value: string | undefined) => {
                              set("addresseeId", value ?? "");
                            }}
                          />
                        </Field>
                      </div>
                      <Checkbox
                        checked={values.urgent}
                        onChange={(event) => {
                          set("urgent", event.target.checked);
                        }}
                      >
                        {t("letters:register.urgent")}
                      </Checkbox>
                      {canLink ? (
                        <Field
                          id="reg-deal"
                          label={t("letters:register.deal.label")}
                          hint={t("letters:register.deal.hint")}
                        >
                          <DealField
                            id="reg-deal"
                            value={values.deal}
                            onChange={(choice) => {
                              set("deal", choice);
                            }}
                            describedBy="reg-deal-hint"
                            invalid={false}
                          />
                        </Field>
                      ) : null}
                      <Field
                        id={id("related_number")}
                        label={t("letters:register.related.label")}
                        hint={t("letters:register.related.hint")}
                        error={fieldError("related_number")}
                      >
                        <Input
                          id={id("related_number")}
                          value={values.relatedNumber}
                          maxLength={32}
                          autoComplete="off"
                          placeholder="IN-101/26"
                          status={errors.related_number ? "error" : undefined}
                          aria-invalid={errors.related_number || undefined}
                          aria-describedby={describedBy(
                            id("related_number"),
                            true,
                            Boolean(errors.related_number),
                          )}
                          onChange={(event) => {
                            set("relatedNumber", event.target.value);
                          }}
                        />
                      </Field>
                      <fieldset className="pf-reg-draft" aria-describedby="reg-draft-hint">
                        <legend>{t("letters:register.draft.legend")}</legend>
                        <p className="pf-hint" id="reg-draft-hint">
                          {t("letters:register.draft.hint")}
                        </p>
                        <div className="pf-newdoc-row">
                          <Field id="reg-draft-kind" label={t("letters:register.draft.kind")}>
                            <Select
                              id="reg-draft-kind"
                              value={values.draftKind || ""}
                              options={[
                                { value: "", label: t("letters:register.draft.none") },
                                ...RESOLUTION_KINDS.map((kind) => ({
                                  value: kind,
                                  label: resolutionKindName(kind),
                                })),
                              ]}
                              onChange={(kind: LetterResolutionKind | "") => {
                                setValues((prev) => ({
                                  ...prev,
                                  draftKind: kind,
                                  // шаблон текста по типу, пока текст не правили (как в форме резолюции)
                                  draftText:
                                    kind &&
                                    (prev.draftText === "" ||
                                      RESOLUTION_KINDS.some(
                                        (k) => t(`letters:office.template.${k}`) === prev.draftText,
                                      ))
                                      ? t(`letters:office.template.${kind}`)
                                      : prev.draftText,
                                }));
                              }}
                            />
                          </Field>
                          {values.draftKind && values.draftKind !== "info" ? (
                            <Field
                              id="reg-draft-responsible"
                              label={t("letters:office.responsible.label")}
                              hint={t("letters:office.responsible.hint")}
                            >
                              <Select
                                id="reg-draft-responsible"
                                value={values.draftResponsibleId || undefined}
                                placeholder={t("letters:office.responsible.choose")}
                                allowClear
                                showSearch
                                optionFilterProp="label"
                                options={people}
                                aria-describedby="reg-draft-responsible-hint"
                                onChange={(value: string | undefined) => {
                                  set("draftResponsibleId", value ?? "");
                                }}
                              />
                            </Field>
                          ) : null}
                          <Field
                            id="reg-draft-acquaint"
                            label={t("letters:register.draft.acquaint")}
                            hint={t("letters:register.draft.acquaintHint")}
                          >
                            <Select
                              id="reg-draft-acquaint"
                              mode="multiple"
                              value={values.draftAcquaintIds}
                              showSearch
                              optionFilterProp="label"
                              options={people}
                              aria-describedby="reg-draft-acquaint-hint"
                              onChange={(ids: string[]) => {
                                set("draftAcquaintIds", ids);
                              }}
                            />
                          </Field>
                        </div>
                        {values.draftKind ? (
                          <div className="pf-newdoc-row">
                            {values.draftKind !== "info" ? (
                              <Field id="reg-draft-due" label={t("letters:office.due.label")}>
                                <DateField
                                  id="reg-draft-due"
                                  value={values.draftDue}
                                  min={today}
                                  onChange={(next) => {
                                    set("draftDue", next);
                                  }}
                                />
                              </Field>
                            ) : null}
                            <Field id="reg-draft-text" label={t("letters:office.text.label")}>
                              <Input.TextArea
                                id="reg-draft-text"
                                value={values.draftText}
                                maxLength={4000}
                                autoSize={{ minRows: 2, maxRows: 6 }}
                                onChange={(event) => {
                                  set("draftText", event.target.value);
                                }}
                              />
                            </Field>
                          </div>
                        ) : null}
                      </fieldset>
                    </div>
                  ),
                },
                {
                  key: "review",
                  title: t("letters:register.sections.review"),
                  content: (
                    <div className="pf-newdoc-actions">
                      <DefinitionList
                        className="pf-reg-summary"
                        columns="auto"
                        items={summaryItems}
                      />
                      <StepRemaining
                        id="reg-remaining"
                        items={remaining}
                        onGo={(step) => {
                          setActive(step as SectionKey);
                        }}
                      />
                      {note ? <ErrorNote message={note} /> : null}
                      <div className="pf-fp-row">
                        <Button
                          type="primary"
                          htmlType="submit"
                          loading={pending}
                          disabled={remaining.length > 0}
                          aria-describedby={remaining.length > 0 ? "reg-remaining" : undefined}
                        >
                          {t("letters:register.submit")}
                        </Button>
                        <Button
                          htmlType="button"
                          disabled={pending}
                          onClick={() => {
                            clearRegisterDraft(userId); // «Отмена» — осознанный отказ: черновик стирается
                            void navigate("/eds/inbox");
                          }}
                        >
                          {t("letters:register.cancel")}
                        </Button>
                      </div>
                    </div>
                  ),
                },
              ]}
            />
          </Card>
        </form>
      </SuggestedFields.Provider>
    </div>
  );
}
