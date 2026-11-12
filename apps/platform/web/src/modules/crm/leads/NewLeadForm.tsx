import { Button, Input, Radio } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import { useCreateCrmLead } from "../../../shared/api/generated/platform-bff";
import type { LeadIn, LeadInSource } from "../../../shared/api/generated/model";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { useRefreshCrm } from "../common/params";

import "../crm.css";

const SOURCES: readonly LeadInSource[] = ["phone", "email", "referral"];
const LANGUAGES = ["ru", "uz", "en"] as const;
type Field = "name" | "phone" | "email" | "company" | "need";

interface Duplicate {
  lead?: string;
  clientId?: number;
}

function duplicateOf(error: unknown): Duplicate | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const lead = error.details["lead"];
  const client = error.details["client_id"];
  if (typeof lead === "string") return { lead };
  if (typeof client === "number") return { clientId: client };
  return null;
}

function fieldsOf(error: unknown): Field[] {
  if (!(error instanceof ApiError)) return [];
  const fields = error.details["fields"];
  return Array.isArray(fields) ? fields.filter((f): f is Field => typeof f === "string") : [];
}

/**
 * «Создать · Лид» (план 2026-11-12 п. 0.1, находка FR-3): звонок, письмо или рекомендация; создавший — ответственный.
 * Нужен телефон или почта — проверяет CRM; такой контакт уже есть — ссылка на найденный лид или клиента.
 */
export function NewLeadForm({ onCancel }: { onCancel: () => void }) {
  const { t } = useTranslation("leads");
  const { mobile } = useViewport();
  const navigate = useNavigate();
  const refresh = useRefreshCrm();
  const base = useId();
  const id = (name: string) => `${base}-${name}`;
  const [form, setForm] = useState<
    Required<Pick<LeadIn, "source" | "language">> & Record<Field, string>
  >({
    source: "phone",
    language: "ru",
    name: "",
    company: "",
    phone: "",
    email: "",
    need: "",
  });
  const [tried, setTried] = useState(false);
  const create = useCreateCrmLead();
  const set = (patch: Partial<typeof form>) => {
    setForm((prev) => ({ ...prev, ...patch }));
  };

  const nameMissing = tried && form.name.trim() === "";
  const duplicate = duplicateOf(create.error);
  const badFields = duplicate ? [] : fieldsOf(create.error);
  const fieldError = (field: Field): string | undefined => {
    if (field === "name" && nameMissing) return t("newLead.errors.name");
    if (badFields.includes(field))
      return t(`newLead.errors.${field === "email" ? "email" : "phone"}`);
    return undefined;
  };
  const generic =
    create.error && !duplicate && badFields.length === 0 ? t("newLead.errors.generic") : null;

  const submit = () => {
    if (create.isPending) return;
    setTried(true);
    if (form.name.trim() === "") return;
    const text = (value: string) => value.trim() || null;
    create.mutate(
      {
        data: {
          source: form.source,
          language: form.language,
          name: form.name.trim(),
          company: text(form.company),
          phone: text(form.phone),
          email: text(form.email),
          need: text(form.need),
        },
      },
      {
        onSuccess: (result) => {
          refresh();
          void navigate(`/crm/leads?lead=${result.lead}&panel=open&tab=card`, { replace: true });
        },
      },
    );
  };

  const input = (field: Field, extra: Partial<Parameters<typeof Input>[0]> = {}) => {
    const error = fieldError(field);
    return (
      <FormField id={id(field)} label={t(`newLead.fields.${field}`)}>
        <Input
          id={id(field)}
          value={form[field]}
          status={error ? "error" : undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id(field)}-error` : undefined}
          onChange={(event) => {
            set({ [field]: event.target.value });
          }}
          {...extra}
        />
        {error ? (
          <span id={`${id(field)}-error`} className="pf-req-error" role="alert">
            {error}
          </span>
        ) : null}
      </FormField>
    );
  };

  return (
    <form
      className="pf-fp-stack"
      noValidate
      aria-labelledby={id("title")}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <h3 className={mobile ? "pf-sr-only" : "pf-fp-title"} id={id("title")}>
        {t("newLead.title")}
      </h3>
      <FormField id={id("source")} label={t("newLead.fields.source")}>
        <Radio.Group
          id={id("source")}
          optionType="button"
          value={form.source}
          onChange={(event) => {
            set({ source: event.target.value as LeadInSource });
          }}
          options={SOURCES.map((source) => ({
            value: source,
            label: t(`newLead.sources.${source}`),
          }))}
        />
      </FormField>
      {input("name", { autoComplete: "name" })}
      {input("company", { autoComplete: "organization" })}
      {input("phone", { autoComplete: "tel", inputMode: "tel" })}
      {input("email", { autoComplete: "email", inputMode: "email" })}
      <FormField id={id("need")} label={t("newLead.fields.need")}>
        <Input.TextArea
          id={id("need")}
          rows={3}
          value={form.need}
          onChange={(event) => {
            set({ need: event.target.value });
          }}
        />
      </FormField>
      <FormField id={id("language")} label={t("newLead.fields.language")}>
        <Radio.Group
          id={id("language")}
          optionType="button"
          value={form.language}
          onChange={(event) => {
            set({ language: event.target.value as LeadIn["language"] & string });
          }}
          options={LANGUAGES.map((language) => ({
            value: language,
            label: t(`newLead.languages.${language}`),
          }))}
        />
      </FormField>

      {duplicate ? (
        <p className="pf-req-error" role="alert">
          {duplicate.lead ? (
            <>
              {t("newLead.errors.leadExists")}{" "}
              <Link to={`/crm/leads?lead=${duplicate.lead}&panel=open&tab=card`}>
                {duplicate.lead}
              </Link>
            </>
          ) : (
            <>
              {t("newLead.errors.clientExists")}{" "}
              <Link to={`/crm/clients?client=${String(duplicate.clientId)}&panel=open&tab=card`}>
                {t("newLead.errors.openClient")}
              </Link>
            </>
          )}
        </p>
      ) : null}
      <ErrorNote message={generic} />

      <div className="pf-crm-actions" data-sheet={mobile}>
        <Button type="primary" htmlType="submit" loading={create.isPending}>
          {t("newLead.submit")}
        </Button>
        <Button onClick={onCancel}>{t("newLead.cancel")}</Button>
      </div>
    </form>
  );
}
