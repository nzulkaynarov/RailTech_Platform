import { Alert, App, Button, Card, Checkbox, Input, Select } from "antd";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { LetterResolutionKind } from "../../../shared/api/generated/model";
import {
  registerLetter,
  useFindLetterDuplicates,
  useListEdsStaff,
  useListLetterKinds,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { DateField } from "../../../shared/ui/DateField";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { letterPath, useRefreshLetters } from "../inbox/api";
import { useRefreshMail } from "../mail/mailModel";
import { RESOLUTION_KINDS } from "../inbox/officeModel";
import { AttachmentsField } from "../new/AttachmentsField";
import { DealField } from "../new/DealField";
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
import { useMailPrefill } from "./useMailPrefill";

import "../new/new.css";
import "./register.css";

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

function describedBy(id: string, hint: boolean, error: boolean): string | undefined {
  const parts = [error ? `${id}-error` : "", hint ? `${id}-hint` : ""].filter(Boolean);
  return parts.length > 0 ? parts.join(" ") : undefined;
}

function newKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

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

/** Задержка ввода для проверки дубля: запрос — когда сотрудник перестал печатать. */
function useSettled(value: string, ms = 400): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSettled(value);
    }, ms);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, ms]);
  return settled;
}

/** Предупреждение «Возможно, уже зарегистрировано» (корреспондент + исх. №): ссылка на существующий ВХ, регистрации не мешает. */
function DuplicateWarning({ sender, refNumber }: { sender: string; refNumber: string }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const name = useSettled(sender.trim());
  const number = useSettled(refNumber.trim());
  const ready = name.length > 0 && number.length > 0;
  const query = useFindLetterDuplicates(
    { ref_number: number || "-", sender_name: name || undefined },
    { query: { enabled: ready, staleTime: 30_000 } },
  );
  const found = ready ? (query.data?.items ?? []) : [];
  if (found.length === 0) return null;
  return (
    <Alert
      type="warning"
      showIcon
      role="status"
      message={t("register.duplicate.title")}
      description={
        <ul className="pf-reg-duplicates">
          {found.map((item) => (
            <li key={item.id}>
              <Link className="pf-focusable" to={letterPath(item.number)}>
                {item.number}
              </Link>{" "}
              {t("register.duplicate.item", {
                subject: item.subject,
                date: date(item.received_at),
              })}
            </li>
          ))}
        </ul>
      }
    />
  );
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
  const [errors, setErrors] = useState<RegisterErrors>({});
  const [note, setNote] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const idempotency = useRef<{ body: string; key: string } | null>(null);
  const [params] = useSearchParams();
  const mailParam = Number(params.get("mail"));
  const mailId = Number.isInteger(mailParam) && mailParam > 0 ? mailParam : null;
  const applyMail = useCallback((update: (prev: RegisterValues) => RegisterValues) => {
    setValues(update);
  }, []);
  const fromMail = useMailPrefill(mailId, applyMail);
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

  const set = <K extends keyof RegisterValues>(key: K, value: RegisterValues[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };
  const setAttachments = (updater: (prev: Attachment[]) => Attachment[]) => {
    setValues((prev) => ({ ...prev, attachments: updater(prev.attachments) }));
  };
  const fieldError = (field: RegisterField) =>
    errors[field] ? t(`letters:register.errors.${field}`) : undefined;
  const focus = (field: RegisterField) => {
    window.setTimeout(() => {
      document.getElementById(registerFieldId(field))?.focus();
    }, 0);
  };

  const submit = async () => {
    const found = validateRegister(values, today);
    setErrors(found);
    setNote(null);
    const first = REGISTER_ORDER.find((field) => found[field]);
    if (first) {
      focus(first);
      return;
    }
    const body = toRegisterBody(values);
    const json = JSON.stringify(body);
    if (idempotency.current?.body !== json) idempotency.current = { body: json, key: newKey() };
    setPending(true);
    try {
      const card = await registerLetter(body, {
        headers: { "Idempotency-Key": idempotency.current.key },
      });
      void refresh();
      if (values.sourceMailId !== null) void refreshMail();
      void message.success(t("letters:register.toast", { number: card.number }));
      const search = new URLSearchParams({ letter: card.number, tab: "resolution" });
      if (mobile) search.set("sheet", "resolution");
      else search.set("panel", "open");
      void navigate({ pathname: "/eds/inbox", search: `?${search.toString()}` });
    } catch (error) {
      const fields = serverFields(error);
      setErrors(Object.fromEntries(fields.map((field) => [field, true])));
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
      <PageHeader title={title} subtitle={t("letters:register.subtitle")} />
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
              <Consequence
                title={t("letters:mail.actions.what")}
                items={[t("letters:mail.busy.what", { name: fromMail.holder.name })]}
              />
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
      <form
        aria-label={t("letters:register.formLabel")}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!pending && !uploading) void submit();
        }}
      >
        <Card>
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
                  aria-describedby={describedBy(id("kind"), kinds.isError, Boolean(errors.kind))}
                  onChange={(code: string) => {
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
                hint={methods.isError ? t("letters:register.method.unavailable") : undefined}
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
                hint={t("letters:register.sender.hint")}
                error={fieldError("sender_name")}
              >
                <Input
                  id={id("sender_name")}
                  value={values.senderName}
                  maxLength={255}
                  autoComplete="off"
                  status={errors.sender_name ? "error" : undefined}
                  aria-invalid={errors.sender_name || undefined}
                  aria-describedby={describedBy(
                    id("sender_name"),
                    true,
                    Boolean(errors.sender_name),
                  )}
                  onChange={(event) => {
                    set("senderName", event.target.value);
                  }}
                />
              </Field>
              <Field
                id={id("sender_inn")}
                label={t("letters:register.inn.label")}
                error={fieldError("sender_inn")}
              >
                <Input
                  id={id("sender_inn")}
                  value={values.senderInn}
                  maxLength={14}
                  inputMode="numeric"
                  autoComplete="off"
                  status={errors.sender_inn ? "error" : undefined}
                  aria-invalid={errors.sender_inn || undefined}
                  aria-describedby={describedBy(
                    id("sender_inn"),
                    false,
                    Boolean(errors.sender_inn),
                  )}
                  onChange={(event) => {
                    set("senderInn", event.target.value);
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
            <DuplicateWarning sender={values.senderName} refNumber={values.refNumber} />
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
                aria-describedby={describedBy(id("subject"), false, Boolean(errors.subject))}
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
            <div className="pf-newdoc-row">
              <Field
                id="reg-document-due"
                label={t("letters:register.documentDue.label")}
                hint={t("letters:register.documentDue.hint")}
              >
                <DateField
                  id="reg-document-due"
                  value={values.documentDue}
                  aria-describedby="reg-document-due-hint"
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
                placeholder="ВХ-101/26"
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
            <Consequence
              items={t("letters:register.consequence", { returnObjects: true }) as string[]}
            />
          </div>
        </Card>
        <div className="pf-newdoc-actions">
          {Object.keys(errors).length > 0 && !note ? (
            <ErrorNote message={t("letters:register.summaryError")} />
          ) : null}
          {note ? <ErrorNote message={note} /> : null}
          <div className="pf-fp-row">
            <Button
              type="primary"
              htmlType="submit"
              loading={pending}
              disabled={uploading}
              title={uploading ? t("documents:form.submit.uploadWait") : undefined}
            >
              {t("letters:register.submit")}
            </Button>
            <Button
              htmlType="button"
              disabled={pending}
              onClick={() => {
                void navigate("/eds/inbox");
              }}
            >
              {t("letters:register.cancel")}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
