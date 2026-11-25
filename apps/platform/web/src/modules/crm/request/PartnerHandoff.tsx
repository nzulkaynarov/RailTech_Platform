import { Button, Input, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import type { LeadCard, PartnerHandoffView } from "../../../shared/api/generated/model";
import { useHandOverCrmLeadAsPartner } from "../../../shared/api/generated/platform-bff";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { reasonError } from "../common/errors";
import { useRefreshCrm } from "../common/params";

import "../crm.css";

/** Страны, из которых чаще всего пишут кандидаты; название — на языке интерфейса. */
const COUNTRIES = ["UZ", "KZ", "KG", "TJ", "RU", "BY", "CN", "TR", "DE", "AE", "IN", "KR"] as const;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

type Field = "company" | "contact" | "offer" | "channel" | "email";

/**
 * «Кто это?» → «Партнёр» (ЛП-1): заявка кандидата в партнёры из карточки лида — компания, страна, ИНН, контакт и что
 * предлагает; заполнено из лида. Повторное нажатие (двойной клик, вторая вкладка) CRM отдаёт ту же заявку. Ошибка оставляет
 * введённое.
 */
export function PartnerHandoff({ lead, onCancel }: { lead: LeadCard; onCancel: () => void }) {
  const { t, i18n } = useTranslation(["request", "clients"]);
  const { me } = useAuth();
  const { mobile } = useViewport();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;
  const refresh = useRefreshCrm();
  const send = useHandOverCrmLeadAsPartner();
  const [values, setValues] = useState({
    company: lead.facts.company ?? lead.contacts.company ?? "",
    country: "UZ",
    inn: "",
    contact: lead.name,
    email: lead.contacts.email ?? "",
    phone: lead.contacts.phone ?? "",
    offer: lead.need ?? "",
  });
  const [tried, setTried] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [done, setDone] = useState<PartnerHandoffView | null>(null);
  const set = (change: Partial<typeof values>) => {
    setValues((prev) => ({ ...prev, ...change }));
  };

  const errors: Partial<Record<Field, string>> = {};
  if (!values.company.trim()) errors.company = "company";
  if (!values.contact.trim()) errors.contact = "contact";
  if (!values.offer.trim()) errors.offer = "offer";
  if (!values.email.trim() && !values.phone.trim()) errors.channel = "channel";
  else if (values.email.trim() && !EMAIL.test(values.email.trim())) errors.email = "email";
  const shown = (field: Field) => (tried && errors[field] ? errors[field] : undefined);
  const text = (field: Field) => {
    const key = shown(field);
    return key ? t(`request:partner.errors.${key}`) : undefined;
  };

  if (done) {
    return (
      <div className="pf-fp-stack" role="status">
        <h3 className="pf-fp-title">{t("request:partner.done.title")}</h3>
        <p className="pf-fp-sub">
          {done.created ? t("request:partner.done.text") : t("request:partner.done.repeated")}
        </p>
        <div className="pf-crm-actions" data-sheet={mobile}>
          {canEdit(me, "erp.stock") ? (
            <LinkButton type="primary" to="/crm/clients?kind=applications">
              {t("request:partner.done.open")}
            </LinkButton>
          ) : null}
          <Button onClick={onCancel}>{t("request:partner.done.close")}</Button>
        </div>
      </div>
    );
  }

  const submit = () => {
    if (send.isPending) return;
    setServerError(null);
    setTried(true);
    if (Object.keys(errors).length > 0) return;
    send.mutate(
      {
        lead: lead.lead,
        data: {
          company_name: values.company.trim(),
          country: values.country,
          inn: values.inn.trim(),
          offer: values.offer.trim(),
          contact_name: values.contact.trim(),
          email: values.email.trim(),
          phone: values.phone.trim(),
        },
      },
      {
        onSuccess: (result) => {
          refresh();
          setDone(result);
        },
        onError: (error) => {
          setServerError(reasonError(t, "request:partner.errors", error));
        },
      },
    );
  };

  const invalid = (field: Field) => (shown(field) ? true : undefined);
  return (
    <form
      className="pf-fp-stack"
      noValidate
      aria-label={t("request:partner.title")}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <p className="pf-fp-sub">{t("request:partner.intro")}</p>
      <FormField id={id("company")} label={t("request:partner.company")}>
        <Input
          id={id("company")}
          value={values.company}
          maxLength={255}
          aria-invalid={invalid("company")}
          onChange={(event) => {
            set({ company: event.target.value });
          }}
        />
        <PartnerError id={id("company-error")} text={text("company")} />
      </FormField>
      <div className="pf-fp-row">
        <FormField id={id("country")} label={t("request:partner.country")}>
          <Select
            id={id("country")}
            showSearch
            optionFilterProp="label"
            value={values.country}
            style={{ minWidth: 180 }}
            onChange={(value: string) => {
              set({ country: value });
            }}
            options={COUNTRIES.map((code) => ({
              value: code,
              label: countryName(code, i18n.language),
            }))}
          />
        </FormField>
        <FormField id={id("inn")} label={t("request:partner.inn")}>
          <Input
            id={id("inn")}
            value={values.inn}
            maxLength={32}
            onChange={(event) => {
              set({ inn: event.target.value });
            }}
          />
        </FormField>
      </div>
      <FormField id={id("contact")} label={t("request:partner.contact")}>
        <Input
          id={id("contact")}
          value={values.contact}
          maxLength={255}
          aria-invalid={invalid("contact")}
          onChange={(event) => {
            set({ contact: event.target.value });
          }}
        />
        <PartnerError id={id("contact-error")} text={text("contact")} />
      </FormField>
      <FormField
        id={id("email")}
        label={t("request:partner.email")}
        hint={t("request:partner.channelsHint")}
      >
        <Input
          id={id("email")}
          type="email"
          value={values.email}
          maxLength={254}
          aria-invalid={invalid("channel") ?? invalid("email")}
          aria-describedby={`${id("email")}-hint`}
          onChange={(event) => {
            set({ email: event.target.value });
          }}
        />
        <PartnerError id={id("email-error")} text={text("email") ?? text("channel")} />
      </FormField>
      <FormField id={id("phone")} label={t("request:partner.phone")}>
        <Input
          id={id("phone")}
          type="tel"
          value={values.phone}
          maxLength={32}
          aria-invalid={invalid("channel")}
          onChange={(event) => {
            set({ phone: event.target.value });
          }}
        />
      </FormField>
      <FormField id={id("offer")} label={t("request:partner.offer")}>
        <Input.TextArea
          id={id("offer")}
          rows={4}
          maxLength={4000}
          value={values.offer}
          aria-invalid={invalid("offer")}
          onChange={(event) => {
            set({ offer: event.target.value });
          }}
        />
        <PartnerError id={id("offer-error")} text={text("offer")} />
      </FormField>
      <ErrorNote message={serverError} />
      <div className="pf-crm-actions" data-sheet={mobile}>
        <Button type="primary" htmlType="submit" loading={send.isPending}>
          {send.isPending ? t("request:partner.submitting") : t("request:partner.submit")}
        </Button>
        <Button onClick={onCancel}>{t("request:partner.cancel")}</Button>
      </div>
    </form>
  );
}

function PartnerError({ id, text }: { id: string; text: string | undefined }) {
  if (!text) return null;
  return (
    <span id={id} className="pf-req-error" role="alert">
      {text}
    </span>
  );
}

function countryName(code: string, language: string): string {
  try {
    return new Intl.DisplayNames([language], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}
