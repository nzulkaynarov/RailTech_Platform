import { App, Button, Card, Input, Select, Skeleton } from "antd";
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
  useGetEdsDocument,
  useUpdateEdsDocument,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { Consequence } from "../../../shared/ui/Consequence";
import { ContextualSaveBar } from "../../../shared/ui/ContextualSaveBar";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import {
  type FieldKey,
  fieldText,
  reasonText,
  savedDocumentId,
  serverFields,
} from "../documents/errors";
import { parseDocumentId, useRefreshDocuments } from "../documents/params";
import { AttachmentsField } from "./AttachmentsField";
import { DealField } from "./DealField";
import {
  type Attachment,
  EMPTY_FORM,
  FIELD_ORDER,
  type FormErrors,
  type FormValues,
  consequenceKey,
  fieldElementId,
  fromDocument,
  isLetter,
  kindFromParam,
  routeKind,
  todayInCompanyZone,
  toCreateBody,
  toUpdateBody,
  validate,
} from "./formModel";

import "../documents/documents.css";
import "./new.css";

const KINDS: readonly EdsDocumentKind[] = ["memo", "application", "report", "letter_out"];

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

/**
 * Форма документа (SPEC-v3 §3.2, §7.3): тип, тема, кому, текст, сумма и «нужно до», вложения, связь с проектом. Главная
 * кнопка отправляет на согласование (письмо — регистрирует), вторичная сохраняет черновик. Ошибка сервера — «Не отправлено:
 * причина», введённое остаётся; если документ уже создан, а отправка отклонена, следующая попытка идёт по тому же черновику.
 */
function DocumentForm({ initial, draft }: { initial: FormValues; draft: EdsDocument | null }) {
  const { t } = useTranslation(["documents", "modules"]);
  const { me } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { mobile } = useViewport();
  const refresh = useRefreshDocuments();
  const canLetter = canEdit(me, "eds.inbox");
  const canLink = canSee(me, { anyOf: ["crm.clients", "eds.projects"] });
  const [values, setValues] = useState<FormValues>(() => ({
    ...initial,
    kind: initial.kind === "letter_out" && !canLetter && !draft ? "memo" : initial.kind,
  }));
  const [errors, setErrors] = useState<FormErrors>({});
  const [note, setNote] = useState<ServerNote | null>(null);
  const [savedId, setSavedId] = useState<string | null>(draft?.id ?? null);
  const [creating, setCreating] = useState(false);
  // Ключ повтора создания: на экземпляр формы и тело запроса — потерянный ответ не заведёт второй документ.
  const idempotency = useRef<{ body: string; key: string } | null>(null);
  const update = useUpdateEdsDocument();
  const pending = creating || update.isPending;
  const uploading = values.attachments.some((a) => a.status === "uploading");
  const letter = isLetter(values.kind);
  const today = todayInCompanyZone();

  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };
  const setAttachments = (updater: (prev: Attachment[]) => Attachment[]) => {
    setValues((prev) => ({ ...prev, attachments: updater(prev.attachments) }));
  };

  const run = async (submit: boolean) => {
    const found = validate(values, today);
    setErrors(found);
    setNote(null);
    const first = FIELD_ORDER.find((field) => found[field]);
    if (first) {
      focusField(first);
      return;
    }
    try {
      let doc: EdsDocument;
      if (savedId) {
        doc = await update.mutateAsync({ id: savedId, data: toUpdateBody(values, submit) });
      } else {
        const body = toCreateBody(values, submit);
        const json = JSON.stringify(body);
        if (idempotency.current?.body !== json) idempotency.current = { body: json, key: newKey() };
        setCreating(true);
        try {
          doc = await createEdsDocument(body, {
            headers: { "Idempotency-Key": idempotency.current.key },
          });
        } finally {
          setCreating(false);
        }
      }
      refresh();
      void message.success(
        !submit
          ? t("documents:form.toast.draft")
          : t(letter ? "documents:form.toast.registered" : "documents:form.toast.sent", {
              number: doc.number ?? "",
            }),
      );
      void navigate({
        pathname: "/eds/documents",
        search: `?scope=mine&doc=${doc.id}${mobile ? "" : "&panel=open"}`,
      });
    } catch (error) {
      const id = savedDocumentId(error);
      if (id) setSavedId(id);
      if (id || savedId) refresh();
      const fields = serverFields(error);
      setErrors(Object.fromEntries(fields.map((field) => [field, true])));
      setNote({
        text: t(submit ? "documents:form.error.send" : "documents:form.error.save", {
          reason: reasonText(t, error),
        }),
        saved: error instanceof ApiError && error.details["saved"] === true,
      });
      const firstField = FIELD_ORDER.find((field) => fields.includes(field));
      if (firstField) focusField(firstField);
    }
  };

  const ids = {
    kind: "doc-kind",
    subject: fieldElementId("subject"),
    text: fieldElementId("text"),
    amount: fieldElementId("amount"),
    due: fieldElementId("due_date"),
    recipient: fieldElementId("recipient"),
    deal: fieldElementId("erp_deal_id"),
    files: "doc-files",
  };
  const route = routeKind(values);
  const routeText = t(`documents:form.route.${route}`);
  const returned = draft?.status === "returned";
  const subtitle = draft
    ? t(returned ? "documents:form.subtitleReturned" : "documents:form.subtitleContinue", {
        number: draft.number ?? "",
      })
    : t(letter ? "documents:form.subtitleLetter" : "documents:form.subtitle");
  const title = t("modules:eds.sections.new");
  useDocumentTitle(title);
  const consequence = t(`documents:form.consequence.${consequenceKey(values)}`, {
    returnObjects: true,
  }) as string[];

  return (
    <div className="pf-newdoc">
      <PageHeader title={title} subtitle={subtitle} />
      <form
        aria-label={t("documents:form.formLabel")}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!pending && !uploading) void run(true);
        }}
      >
        <ContextualSaveBar
          visible={Boolean(values.subject || values.amount || values.attachments.length)}
          loading={pending}
          onSave={() => {
            if (!pending && !uploading) void run(true);
          }}
          onDiscard={() => {
            void navigate("/eds/documents");
          }}
        />
        <Card>
          <div className="pf-fp-form">
            <Field
              id={ids.kind}
              label={t("documents:form.type.label")}
              hint={
                draft || savedId
                  ? t("documents:form.type.locked")
                  : canLetter
                    ? undefined
                    : t("documents:form.type.letterLocked")
              }
            >
              <Select
                id={ids.kind}
                value={values.kind}
                disabled={draft !== null || savedId !== null}
                options={KINDS.map((kind) => ({
                  value: kind,
                  disabled: kind === "letter_out" && !canLetter,
                  label:
                    kind === "letter_out" && !canLetter
                      ? t("documents:form.type.letterOption")
                      : t(`documents:kinds.${kind}`),
                }))}
                onChange={(kind) => {
                  setErrors({});
                  set("kind", kind);
                }}
              />
            </Field>
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
              </>
            ) : (
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
            )}
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
            {letter ? null : (
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
                  <Input
                    id={ids.due}
                    type="date"
                    min={today}
                    value={values.dueDate}
                    status={errors.due_date ? "error" : undefined}
                    aria-invalid={errors.due_date || undefined}
                    aria-describedby={describedBy(ids.due, true, Boolean(errors.due_date))}
                    onChange={(event) => {
                      set("dueDate", event.target.value);
                    }}
                  />
                </Field>
              </div>
            )}
            <Field
              id={ids.files}
              label={t("documents:form.files.label")}
              hint={t("documents:form.files.hint")}
            >
              <AttachmentsField
                id={ids.files}
                value={values.attachments}
                onChange={setAttachments}
              />
            </Field>
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
            <div className="pf-newdoc-route">
              <span className="pf-fp-label">{t("documents:form.route.label")}</span>
              <span>{routeText}</span>
            </div>
            <Consequence items={consequence} />
            <p className="pf-hint">{t("documents:form.consequence.draft")}</p>
          </div>
        </Card>
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
              {t(letter ? "documents:form.submit.letter" : "documents:form.submit.approval")}
            </Button>
            <Button
              htmlType="button"
              disabled={pending || uploading}
              onClick={() => {
                void run(false);
              }}
            >
              {t("documents:form.submit.draft")}
            </Button>
          </div>
        </div>
      </form>
    </div>
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
    <LinkButton to="/eds/documents?scope=mine">{t("documents:form.toDocuments")}</LinkButton>
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
 * (`/eds/new?draft=<id>`). Документ на бланке с PDF и шаблонами — волна D-DOC; здесь простой текст.
 */
export function NewDocumentPage() {
  const [params] = useSearchParams();
  const draft = parseDocumentId(params.get("draft"));
  if (draft) return <ContinueDraft id={draft} />;
  return (
    <DocumentForm
      key={params.get("type") ?? "memo"}
      initial={{ ...EMPTY_FORM, kind: kindFromParam(params.get("type")) }}
      draft={null}
    />
  );
}
