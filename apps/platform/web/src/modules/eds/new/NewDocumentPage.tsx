import { Alert, App, Button, Card, Input, Select, Skeleton } from "antd";
import { type ReactNode, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { EdsDocument, EdsDocumentKind } from "../../../shared/api/generated/model";
import {
  createEdsDocument,
  requestEdsDocumentRegistration,
  useGetEdsDocument,
  useGetEdsLetterhead,
  useGetLetter,
  useListEdsStaff,
  useUpdateEdsDocument,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { BodyEditor } from "../../../shared/ui/BodyEditor/BodyEditor";
import { bodyLang, isBlank } from "../../../shared/ui/BodyEditor/bodyModel";
import { DateField } from "../../../shared/ui/DateField";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { type StepSection, StepSections } from "../../../shared/ui/StepSections/StepSections";
import {
  type FieldKey,
  fieldText,
  reasonText,
  savedDocumentId,
  serverFields,
} from "../documents/errors";
import { LetterPdfPanel } from "../documents/LetterPdfPanel";
import { parseDocumentId, useRefreshDocuments } from "../documents/params";
import { AttachmentsField } from "./AttachmentsField";
import { DealField } from "./DealField";
import {
  type Attachment,
  EMPTY_FORM,
  FIELD_ORDER,
  type FormErrors,
  type FormValues,
  fieldElementId,
  fromDocument,
  isLetter,
  kindFromParam,
  replyPrefill,
  routeKind,
  type SubmitMode,
  todayInCompanyZone,
  toCreateBody,
  toUpdateBody,
  validate,
} from "./formModel";

import "../documents/documents.css";
import "./new.css";

/** Типы внутреннего документа; исходящее письмо — отдельный экран без выбора типа (план 2026-11-12 п. 0.2). */
const INTERNAL_KINDS: readonly EdsDocumentKind[] = ["memo", "application", "report"];

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
  return (
    <div className="pf-fp-field">
      <label htmlFor={id}>{label}</label>
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

/** Случайный ключ повтора; `crypto.randomUUID` есть не везде (небезопасный контекст, старый движок) — запасной путь. */
function newKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
}

function describedBy(id: string, hasHint: boolean, hasError: boolean): string | undefined {
  const parts = [hasError ? `${id}-error` : "", hasHint ? `${id}-hint` : ""].filter(Boolean);
  return parts.length > 0 ? parts.join(" ") : undefined;
}

function focusField(field: FieldKey): void {
  window.setTimeout(() => {
    document.getElementById(fieldElementId(field))?.focus();
  }, 0);
}

interface ServerNote {
  text: string;
  saved: boolean;
}

type SectionKey = "about" | "body" | "route" | "check";
type Action = "draft" | "submit" | "handover";

/**
 * Форма документа (SPEC-v3 §3.2, §7.3): тип, тема, кому, текст, сумма и «нужно до», вложения, связь с проектом. Главная
 * кнопка отправляет на согласование, вторичная сохраняет черновик. Письмо (P4) — на бланке компании: тело блоками, «кому»,
 * почта адресата, подписант и настоящий PDF рядом; держатель «регистрировать входящие» регистрирует ИСХ и отправляет
 * адресату, остальные передают черновик на регистрацию делопроизводителю (B-P8B-4). Ошибка сервера — «Не отправлено:
 * причина», введённое остаётся; если документ уже создан, а отправка отклонена, следующая попытка идёт по тому же черновику.
 */
function DocumentForm({
  initial,
  draft,
  prefilledFrom = null,
}: {
  initial: FormValues;
  draft: EdsDocument | null;
  /** Номер ВХ, из которого заполнены корреспондент, почта и тема (EDS-REPLY-1) */
  prefilledFrom?: string | null;
}) {
  const { t, i18n } = useTranslation(["documents", "modules"]);
  const { me } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { mobile } = useViewport();
  const refresh = useRefreshDocuments();
  // P8: исходящее письмо регистрирует тот, кто регистрирует входящие (`eds.inbox.register`); черновик письма (P4) готовит
  // любой и передаёт делопроизводителю.
  const canRegister = canEdit(me, "eds.inbox.register");
  const canLink = canSee(me, { anyOf: ["crm.clients", "eds.projects"] });
  const canCompany = canEdit(me, "company.settings");
  const [values, setValues] = useState<FormValues>(initial);
  // Пункт 1.6 плана: согласующие и получатели копии — из сотрудников EDS (без автора: он отправляет сам).
  const staff = useListEdsStaff({ query: { staleTime: 5 * 60_000 } });
  const people = (staff.data?.items ?? [])
    .filter((p) => p.id !== me.id)
    .map((p) => ({ value: p.id, label: p.position ? `${p.name} · ${p.position}` : p.name }));
  const [errors, setErrors] = useState<FormErrors>({});
  // Секции по шагам (platform-frontend.md §4.1a): новый документ — с первой, черновик — с проверки.
  const [active, setActive] = useState<SectionKey>(draft ? "check" : "about");
  const [note, setNote] = useState<ServerNote | null>(null);
  const [savedId, setSavedId] = useState<string | null>(draft?.id ?? null);
  // Id сохранённого черновика без ожидания перерисовки: «Показать PDF» сразу после создания идёт по тому же документу.
  const savedRef = useRef<string | null>(draft?.id ?? null);
  const [creating, setCreating] = useState(false);
  const [handingOver, setHandingOver] = useState(false);
  // Ключ повтора создания: на экземпляр формы и тело запроса — потерянный ответ не заведёт второй документ.
  const idempotency = useRef<{ body: string; key: string } | null>(null);
  const update = useUpdateEdsDocument();
  const pending = creating || update.isPending || handingOver;
  const uploading = values.attachments.some((a) => a.status === "uploading");
  const letter = isLetter(values.kind);
  const letterhead = useGetEdsLetterhead({ query: { enabled: letter, staleTime: 60_000 } });
  const today = todayInCompanyZone();
  const lang = bodyLang(i18n.language);
  const handover = letter && !canRegister;
  const sendToRecipient = letter && values.recipientEmail.trim() !== "";

  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };
  const setAttachments = (updater: (prev: Attachment[]) => Attachment[]) => {
    setValues((prev) => ({ ...prev, attachments: updater(prev.attachments) }));
  };

  /** Создать или сохранить документ; `mode` — отправить ли (письмо — зарегистрировать и отправить адресату). */
  const persist = async (mode: SubmitMode): Promise<EdsDocument> => {
    const current = savedRef.current;
    if (current) {
      const doc = await update.mutateAsync({ id: current, data: toUpdateBody(values, mode, lang) });
      return doc;
    }
    const body = toCreateBody(values, mode, lang);
    const json = JSON.stringify(body);
    if (idempotency.current?.body !== json) idempotency.current = { body: json, key: newKey() };
    setCreating(true);
    try {
      const doc = await createEdsDocument(body, {
        headers: { "Idempotency-Key": idempotency.current.key },
      });
      savedRef.current = doc.id;
      setSavedId(doc.id);
      return doc;
    } finally {
      setCreating(false);
    }
  };

  const check = (): boolean => {
    const found = validate(values, today);
    setErrors(found);
    setNote(null);
    const first = FIELD_ORDER.find((field) => found[field]);
    if (first) {
      // Ошибка открывает свою секцию (platform-frontend.md §4.1a), фокус — после отрисовки.
      setActive(first === "text" ? "body" : "about");
      focusField(first);
      return false;
    }
    return true;
  };

  const fail = (error: unknown, submit: boolean) => {
    const id = savedDocumentId(error);
    if (id) {
      savedRef.current = id;
      setSavedId(id);
    }
    if (id || savedRef.current) refresh();
    const fields = serverFields(error);
    setErrors(Object.fromEntries(fields.map((field) => [field, true])));
    if (fields.length > 0) setActive(fields.every((field) => field === "text") ? "body" : "about");
    setNote({
      text: t(submit ? "documents:form.error.send" : "documents:form.error.save", {
        reason: reasonText(t, error),
      }),
      saved: error instanceof ApiError && error.details["saved"] === true,
    });
    const firstField = FIELD_ORDER.find((field) => fields.includes(field));
    if (firstField) focusField(firstField);
  };

  const run = async (action: Action) => {
    if (!check()) return;
    const submit = action !== "draft";
    try {
      let doc = await persist(
        action === "submit" ? { submit: true, send: sendToRecipient } : { submit: false },
      );
      if (action === "handover") {
        setHandingOver(true);
        try {
          doc = await requestEdsDocumentRegistration(doc.id);
        } finally {
          setHandingOver(false);
        }
      }
      refresh();
      const toast =
        action === "draft"
          ? t("documents:form.toast.draft")
          : action === "handover"
            ? t("documents:form.toast.handover")
            : !letter
              ? t("documents:form.toast.sent", { number: doc.number ?? "" })
              : t(
                  sendToRecipient
                    ? "documents:form.toast.registeredSent"
                    : "documents:form.toast.registered",
                  {
                    number: doc.number ?? "",
                  },
                );
      void message.success(toast);
      void navigate({
        pathname: "/eds/documents",
        search: `?box=${letter ? "outgoing" : "internal"}&scope=mine&doc=${doc.id}${mobile ? "" : "&panel=open"}`,
      });
    } catch (error) {
      fail(error, submit);
    }
  };

  /** «Показать PDF»: сохранить черновик (без перехода) и отдать его id блоку PDF. */
  // Страницы строятся сами (пункт «Ш»): незаполненная форма — молча ждём, без ошибок у полей.
  const prepareQuiet = async (): Promise<string | null> => {
    if (Object.keys(validate(values, today)).length > 0 || uploading) return null;
    try {
      const doc = await persist({ submit: false });
      refresh();
      return doc.id;
    } catch {
      return null;
    }
  };

  const prepare = async (): Promise<string | null> => {
    if (!check()) return null;
    try {
      const doc = await persist({ submit: false });
      refresh();
      return doc.id;
    } catch (error) {
      fail(error, false);
      return null;
    }
  };

  const ids = {
    kind: "doc-kind",
    subject: fieldElementId("subject"),
    text: fieldElementId("text"),
    amount: fieldElementId("amount"),
    due: fieldElementId("due_date"),
    recipient: fieldElementId("recipient"),
    email: fieldElementId("recipient_email"),
    deal: fieldElementId("erp_deal_id"),
    replyTo: fieldElementId("in_reply_to_number"),
    files: "doc-files",
  };
  const route = routeKind(values);
  const routeText = t(
    handover ? "documents:form.route.letterHandover" : `documents:form.route.${route}`,
  );
  const returned = draft?.status === "returned";
  const subtitle = draft
    ? t(returned ? "documents:form.subtitleReturned" : "documents:form.subtitleContinue", {
        number: draft.number ?? "",
      })
    : t(
        letter
          ? handover
            ? "documents:form.subtitleLetterHandover"
            : "documents:form.subtitleLetter"
          : "documents:form.subtitle",
      );
  const title = t(letter ? "documents:form.title.letter" : "documents:form.title.internal");
  useDocumentTitle(title);
  const head = letterhead.data;
  const signatoryHint =
    head?.signatory_name && head.signatory_position
      ? t("documents:form.signatory.hint", {
          name: head.signatory_name,
          position: head.signatory_position,
        })
      : t("documents:form.signatory.hintNone");
  const primaryLabel = !letter
    ? t("documents:form.submit.approval")
    : handover
      ? t("documents:form.submit.handover")
      : t(sendToRecipient ? "documents:form.submit.letterSend" : "documents:form.submit.letter");

  const textField = letter ? (
    <Field
      id={ids.text}
      label={t("documents:form.body.label")}
      hint={t("documents:form.body.hint")}
      error={errors.text ? fieldText(t, "text") : undefined}
    >
      <BodyEditor
        id={ids.text}
        label={t("documents:form.body.label")}
        value={values.body}
        invalid={Boolean(errors.text)}
        describedBy={describedBy(ids.text, true, Boolean(errors.text))}
        onChange={(body) => {
          set("body", body);
        }}
      />
    </Field>
  ) : (
    <Field
      id={ids.text}
      label={t("documents:form.text.label")}
      hint={t("documents:form.text.hint")}
      error={errors.text ? fieldText(t, "text") : undefined}
    >
      <Input.TextArea
        id={ids.text}
        rows={8}
        maxLength={20000}
        value={values.text}
        status={errors.text ? "error" : undefined}
        aria-invalid={errors.text || undefined}
        aria-describedby={describedBy(ids.text, true, Boolean(errors.text))}
        onChange={(event) => {
          set("text", event.target.value);
        }}
      />
    </Field>
  );

  const sectionOf = (field: string): SectionKey => (field === "text" ? "body" : "about");
  const invalid = (key: SectionKey) =>
    Object.keys(errors).some((field) => sectionOf(field) === key);

  const aboutSummary = letter
    ? [
        values.recipientName,
        values.recipientEmail,
        values.inReplyTo ? t("documents:form.steps.replyTo", { number: values.inReplyTo }) : "",
      ]
        .filter(Boolean)
        .join(" · ")
    : [
        t(`documents:kinds.${values.kind}`),
        values.subject,
        values.amount ? `${values.amount} ${t("documents:form.steps.currency")}` : "",
      ]
        .filter(Boolean)
        .join(" · ");
  const filesDone = values.attachments.filter((a) => a.status === "done").length;
  const bodyFilled = letter ? !isBlank(values.body) : values.text.trim() !== "";
  const bodySummary = [
    t(bodyFilled ? "documents:form.steps.textFilled" : "documents:form.steps.textEmpty"),
    filesDone > 0 ? t("documents:form.steps.files", { count: filesDone }) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const aboutDone = values.subject.trim() !== "" && (!letter || values.recipientName.trim() !== "");

  const draftButton = (
    <Button
      htmlType="button"
      disabled={pending || uploading}
      onClick={() => {
        void run("draft");
      }}
    >
      {t("documents:form.submit.draft")}
    </Button>
  );

  const reviewRows: { key: SectionKey; title: string; summary: string }[] = [
    {
      key: "about",
      title: t(letter ? "documents:form.steps.aboutLetter" : "documents:form.steps.aboutInternal"),
      summary: aboutSummary,
    },
    { key: "body", title: t("documents:form.steps.body"), summary: bodySummary },
    {
      key: "route",
      title: t(letter ? "documents:form.steps.routeLetter" : "documents:form.steps.routeInternal"),
      summary: routeText,
    },
  ];

  const sections: StepSection[] = [
    {
      key: "about",
      title: t(letter ? "documents:form.steps.aboutLetter" : "documents:form.steps.aboutInternal"),
      summary: aboutSummary,
      complete: aboutDone,
      invalid: invalid("about"),
      footer: draftButton,
      content: (
        <div className="pf-fp-form">
          {letter && handover ? (
            <p className="pf-hint" style={{ margin: 0 }}>
              {t("documents:form.type.letterHandover")}
            </p>
          ) : null}
          {letter ? null : (
            <Field
              id={ids.kind}
              label={t("documents:form.type.label")}
              hint={draft || savedId ? t("documents:form.type.locked") : undefined}
            >
              <Select
                id={ids.kind}
                value={values.kind}
                disabled={draft !== null || savedId !== null}
                options={INTERNAL_KINDS.map((kind) => ({
                  value: kind,
                  label: t(`documents:kinds.${kind}`),
                }))}
                onChange={(kind) => {
                  setErrors({});
                  set("kind", kind);
                }}
              />
            </Field>
          )}
          {letter && letterhead.data && !letterhead.data.configured ? (
            <Alert
              type="warning"
              showIcon
              message={t("documents:form.letterhead.missing")}
              action={
                canCompany ? (
                  <LinkButton size="small" to="/admin/company?part=brand">
                    {t("documents:form.letterhead.open")}
                  </LinkButton>
                ) : undefined
              }
            />
          ) : null}
          <Field
            id={ids.subject}
            label={t("documents:form.subject.label")}
            hint={t("documents:form.subject.hint")}
            error={errors.subject ? fieldText(t, "subject") : undefined}
          >
            <Input
              id={ids.subject}
              value={values.subject}
              maxLength={300}
              autoComplete="off"
              status={errors.subject ? "error" : undefined}
              aria-invalid={errors.subject || undefined}
              aria-describedby={describedBy(ids.subject, true, Boolean(errors.subject))}
              onChange={(event) => {
                set("subject", event.target.value);
              }}
            />
          </Field>
          {letter ? (
            <>
              <Field
                id={ids.recipient}
                label={t("documents:form.recipient.label")}
                error={errors.recipient ? fieldText(t, "recipient") : undefined}
              >
                <Input
                  id={ids.recipient}
                  value={values.recipientName}
                  maxLength={255}
                  autoComplete="off"
                  status={errors.recipient ? "error" : undefined}
                  aria-invalid={errors.recipient || undefined}
                  aria-describedby={describedBy(ids.recipient, false, Boolean(errors.recipient))}
                  onChange={(event) => {
                    set("recipientName", event.target.value);
                  }}
                />
              </Field>
              <div className="pf-newdoc-row">
                <Field
                  id="doc-recipient-inn"
                  label={t("documents:form.recipient.inn")}
                  hint={t("documents:form.recipient.innHint")}
                >
                  <Input
                    id="doc-recipient-inn"
                    value={values.recipientInn}
                    maxLength={32}
                    autoComplete="off"
                    aria-describedby="doc-recipient-inn-hint"
                    onChange={(event) => {
                      set("recipientInn", event.target.value);
                    }}
                  />
                </Field>
                <Field
                  id={ids.email}
                  label={t("documents:form.email.label")}
                  hint={t("documents:form.email.hint")}
                  error={errors.recipient_email ? fieldText(t, "recipient_email") : undefined}
                >
                  <Input
                    id={ids.email}
                    type="email"
                    inputMode="email"
                    value={values.recipientEmail}
                    maxLength={254}
                    autoComplete="off"
                    status={errors.recipient_email ? "error" : undefined}
                    aria-invalid={errors.recipient_email || undefined}
                    aria-describedby={describedBy(ids.email, true, Boolean(errors.recipient_email))}
                    onChange={(event) => {
                      set("recipientEmail", event.target.value);
                    }}
                  />
                </Field>
              </div>
              <Field
                id="doc-recipient-attention"
                label={t("documents:form.attention.label")}
                hint={t("documents:form.attention.hint")}
              >
                <Input
                  id="doc-recipient-attention"
                  value={values.recipientAttention}
                  maxLength={300}
                  autoComplete="off"
                  aria-describedby="doc-recipient-attention-hint"
                  onChange={(event) => {
                    set("recipientAttention", event.target.value);
                  }}
                />
              </Field>
              {prefilledFrom ? (
                <p className="pf-hint" role="status">
                  {t("documents:form.replyPrefilled", { number: prefilledFrom })}
                </p>
              ) : null}
              {draft ? null : (
                <Field
                  id={ids.replyTo}
                  label={t("documents:form.replyTo.label")}
                  hint={t("documents:form.replyTo.hint")}
                  error={errors.in_reply_to_number ? fieldText(t, "in_reply_to_number") : undefined}
                >
                  <Input
                    id={ids.replyTo}
                    value={values.inReplyTo}
                    maxLength={32}
                    autoComplete="off"
                    placeholder="ВХ-112/26"
                    disabled={savedId !== null}
                    status={errors.in_reply_to_number ? "error" : undefined}
                    aria-invalid={errors.in_reply_to_number || undefined}
                    aria-describedby={describedBy(
                      ids.replyTo,
                      true,
                      Boolean(errors.in_reply_to_number),
                    )}
                    onChange={(event) => {
                      set("inReplyTo", event.target.value);
                    }}
                  />
                </Field>
              )}
            </>
          ) : (
            <>
              <Field
                id="doc-to"
                label={t("documents:form.to.label")}
                hint={t("documents:form.to.hint")}
              >
                <Input
                  id="doc-to"
                  value={t("documents:form.to.director")}
                  readOnly
                  aria-describedby="doc-to-hint"
                />
              </Field>
              <div className="pf-newdoc-row">
                <Field
                  id={ids.amount}
                  label={t("documents:form.amount.label")}
                  hint={t(
                    values.kind === "memo"
                      ? "documents:form.amount.hint"
                      : "documents:form.due.hint",
                  )}
                  error={errors.amount ? fieldText(t, "amount") : undefined}
                >
                  <Input
                    id={ids.amount}
                    value={values.amount}
                    inputMode="decimal"
                    autoComplete="off"
                    placeholder="1 500 000"
                    status={errors.amount ? "error" : undefined}
                    aria-invalid={errors.amount || undefined}
                    aria-describedby={describedBy(ids.amount, true, Boolean(errors.amount))}
                    onChange={(event) => {
                      set("amount", event.target.value);
                    }}
                  />
                </Field>
                <Field
                  id={ids.due}
                  label={t("documents:form.due.label")}
                  hint={t("documents:form.due.hint")}
                  error={errors.due_date ? fieldText(t, "due_date") : undefined}
                >
                  <DateField
                    id={ids.due}
                    min={today}
                    value={values.dueDate}
                    status={errors.due_date ? "error" : undefined}
                    aria-invalid={errors.due_date || undefined}
                    aria-describedby={describedBy(ids.due, true, Boolean(errors.due_date))}
                    onChange={(next) => {
                      set("dueDate", next);
                    }}
                  />
                </Field>
              </div>
            </>
          )}
          {canLink ? (
            <Field
              id={ids.deal}
              label={t("documents:form.deal.label")}
              hint={t("documents:form.deal.hint")}
              error={errors.erp_deal_id ? fieldText(t, "erp_deal_id") : undefined}
            >
              <DealField
                id={ids.deal}
                value={values.deal}
                onChange={(choice) => {
                  set("deal", choice);
                }}
                describedBy={describedBy(ids.deal, true, Boolean(errors.erp_deal_id)) ?? ""}
                invalid={Boolean(errors.erp_deal_id)}
              />
            </Field>
          ) : null}
        </div>
      ),
    },
    {
      key: "body",
      title: t("documents:form.steps.body"),
      summary: bodySummary,
      complete: bodyFilled,
      invalid: invalid("body"),
      footer: draftButton,
      content: (
        <div className="pf-fp-form">
          {textField}
          <Field
            id={ids.files}
            label={t("documents:form.files.label")}
            hint={t("documents:form.files.hint")}
          >
            <AttachmentsField id={ids.files} value={values.attachments} onChange={setAttachments} />
          </Field>
        </div>
      ),
    },
    {
      key: "route",
      title: t(letter ? "documents:form.steps.routeLetter" : "documents:form.steps.routeInternal"),
      summary: routeText,
      complete: true,
      footer: draftButton,
      content: (
        <div className="pf-fp-form">
          <div className="pf-newdoc-route">
            <span className="pf-fp-label">{t("documents:form.route.label")}</span>
            <span>{routeText}</span>
          </div>
          {letter ? null : (
            <>
              <Field
                id="doc-approvers"
                label={t("documents:form.route.approvers")}
                hint={t("documents:form.route.approversHint")}
              >
                <Select
                  id="doc-approvers"
                  mode="multiple"
                  value={values.approvers}
                  placeholder={t("documents:form.route.choosePeople")}
                  optionFilterProp="label"
                  options={people}
                  maxCount={10}
                  aria-describedby="doc-approvers-hint"
                  onChange={(next: string[]) => {
                    set("approvers", next);
                  }}
                />
              </Field>
              <Field
                id="doc-watchers"
                label={t("documents:form.route.watchers")}
                hint={t("documents:form.route.watchersHint")}
              >
                <Select
                  id="doc-watchers"
                  mode="multiple"
                  value={values.watchers}
                  placeholder={t("documents:form.route.choosePeople")}
                  optionFilterProp="label"
                  options={people}
                  maxCount={20}
                  aria-describedby="doc-watchers-hint"
                  onChange={(next: string[]) => {
                    set("watchers", next);
                  }}
                />
              </Field>
            </>
          )}
          {letter ? (
            <div className="pf-newdoc-row">
              <Field
                id="doc-signatory-name"
                label={t("documents:form.signatory.name")}
                hint={signatoryHint}
              >
                <Input
                  id="doc-signatory-name"
                  value={values.signatoryName}
                  maxLength={255}
                  autoComplete="off"
                  placeholder={head?.signatory_name ?? undefined}
                  aria-describedby="doc-signatory-name-hint"
                  onChange={(event) => {
                    set("signatoryName", event.target.value);
                  }}
                />
              </Field>
              <Field id="doc-signatory-position" label={t("documents:form.signatory.position")}>
                <Input
                  id="doc-signatory-position"
                  value={values.signatoryPosition}
                  maxLength={255}
                  autoComplete="off"
                  placeholder={head?.signatory_position ?? undefined}
                  onChange={(event) => {
                    set("signatoryPosition", event.target.value);
                  }}
                />
              </Field>
            </div>
          ) : null}
        </div>
      ),
    },
    {
      key: "check",
      title: t("documents:form.steps.check"),
      content: (
        <div className="pf-fp-form">
          <dl className="pf-newdoc-review">
            {reviewRows.map((row) => (
              <div key={row.key} className="pf-newdoc-review-row">
                <dt>{row.title}</dt>
                <dd>{row.summary || "—"}</dd>
                <dd>
                  <Button
                    type="link"
                    size="small"
                    onClick={() => {
                      setActive(row.key);
                    }}
                  >
                    {t("ui:formSteps.edit")}
                  </Button>
                </dd>
              </div>
            ))}
          </dl>
          <p className="pf-hint">{t("documents:form.consequence.draft")}</p>
          <div className="pf-newdoc-actions">
            {Object.keys(errors).length > 0 && !note ? (
              <ErrorNote message={t("documents:form.validation.summary")} />
            ) : null}
            {note ? (
              <ErrorNote
                message={
                  note.saved ? `${note.text}. ${t("documents:form.error.savedNote")}` : note.text
                }
              />
            ) : null}
            <div className="pf-fp-row">
              <Button
                type="primary"
                htmlType="submit"
                loading={pending}
                disabled={uploading}
                title={uploading ? t("documents:form.submit.uploadWait") : undefined}
              >
                {primaryLabel}
              </Button>
              {draftButton}
            </div>
          </div>
        </div>
      ),
    },
  ];

  const form = (
    <form
      aria-label={t("documents:form.formLabel")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!pending && !uploading) void run(handover ? "handover" : "submit");
      }}
    >
      <StepSections
        sections={sections}
        active={active}
        onActiveChange={(key) => {
          setActive(key as SectionKey);
        }}
      />
    </form>
  );

  return (
    <div className={letter ? "pf-newdoc pf-newdoc--letter" : "pf-newdoc"}>
      <PageHeader title={title} subtitle={subtitle} />
      {letter ? (
        <div className="pf-newdoc-letter">
          <div className="pf-newdoc-letter-form">{form}</div>
          <Card className="pf-newdoc-letter-pdf">
            <LetterPdfPanel
              documentId={savedId}
              initial={draft?.letter?.pdf ?? null}
              prepare={prepare}
              canBuild={!uploading}
              subject={values.subject}
              auto={{ key: JSON.stringify(values), prepare: prepareQuiet }}
            />
          </Card>
        </div>
      ) : (
        form
      )}
    </div>
  );
}

/**
 * «Подготовить ответ» с рабочего экрана поручения (EDS-REPLY-1): форма письма уже заполнена из входящего — корреспондент,
 * ИНН, почта (если она есть в письме) и тема «На ВХ-… от …: тема»; всё можно поправить. Письмо не прочиталось — форма с одним
 * номером ВХ, как раньше: путь не обрывается.
 */
function ReplyDraft({ id, number }: { id: string; number: string }) {
  const { t } = useTranslation(["documents", "modules"]);
  const { date } = useFormat();
  const query = useGetLetter(id);
  if (query.isPending) {
    const title = t("documents:form.title.letter");
    return (
      <div className="pf-newdoc">
        <PageHeader title={title} subtitle={t("documents:form.loadDraft")} />
        <Card>
          <Skeleton active paragraph={{ rows: 6 }} title={false} />
        </Card>
      </div>
    );
  }
  const letter = query.data;
  const initial: FormValues = {
    ...EMPTY_FORM,
    kind: "letter_out",
    inReplyTo: letter?.number ?? number,
    ...(letter
      ? replyPrefill(
          letter,
          t("documents:form.replySubject", {
            number: letter.number,
            date: date(letter.received_at),
          }),
        )
      : {}),
  };
  return (
    <DocumentForm
      key={id}
      initial={initial}
      draft={null}
      prefilledFrom={letter ? letter.number : null}
    />
  );
}

function ContinueDraft({ id }: { id: string }) {
  const { t } = useTranslation(["documents", "modules"]);
  const query = useGetEdsDocument(id);
  const title = t("modules:eds.sections.new");
  useDocumentTitle(title);
  if (query.isPending) {
    return (
      <div className="pf-newdoc">
        <PageHeader title={title} subtitle={t("documents:form.loadDraft")} />
        <Card>
          <Skeleton active paragraph={{ rows: 6 }} title={false} />
        </Card>
      </div>
    );
  }
  const back = (
    <LinkButton to="/eds/documents?box=internal&scope=mine">
      {t("documents:form.toDocuments")}
    </LinkButton>
  );
  if (query.isError) {
    return (
      <div className="pf-newdoc">
        <PageHeader title={title} />
        <Card>
          <EmptyState
            title={t("documents:form.draftLoadError.title")}
            text={t("documents:form.draftLoadError.text")}
            action={back}
          />
        </Card>
      </div>
    );
  }
  if (!query.data.can_edit) {
    return (
      <div className="pf-newdoc">
        <PageHeader title={title} />
        <Card>
          <EmptyState
            title={t("documents:form.notEditable.title")}
            text={t("documents:form.notEditable.text")}
            action={back}
          />
        </Card>
      </div>
    );
  }
  return <DocumentForm key={query.data.id} initial={fromDocument(query.data)} draft={query.data} />;
}

/**
 * EDS · «Создать документ» (`/eds/new?type=memo|statement|report|letter`, SPEC-v3 §6.3) и «Продолжить» черновик
 * (`/eds/new?draft=<id>`). Письмо — на бланке компании с настоящим PDF (P4); служебка, заявление и отчёт — простой текст.
 */
export function NewDocumentPage() {
  const [params] = useSearchParams();
  const draft = parseDocumentId(params.get("draft"));
  if (draft) return <ContinueDraft id={draft} />;
  const replyId = parseDocumentId(params.get("reply_id"));
  if (replyId && kindFromParam(params.get("type")) === "letter_out") {
    return <ReplyDraft id={replyId} number={params.get("reply_to")?.trim().slice(0, 32) ?? ""} />;
  }
  return (
    <DocumentForm
      key={params.get("type") ?? "memo"}
      initial={{
        ...EMPTY_FORM,
        kind: kindFromParam(params.get("type")),
        // «Подготовить ответ» с рабочего экрана поручения (P8b): `?type=letter&reply_to=ВХ-112/26`
        inReplyTo: params.get("reply_to")?.trim().slice(0, 32) ?? "",
      }}
      draft={null}
    />
  );
}
