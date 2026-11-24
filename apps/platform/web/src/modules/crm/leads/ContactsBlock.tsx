import { EmailProblem } from "../../../shared/ui/EmailProblem";
import { Alert, Button, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { LeadCard, LeadDuplicate } from "../../../shared/api/generated/model";
import { useUpdateCrmLead } from "../../../shared/api/generated/platform-bff";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { clientPath } from "../common/params";
import { useRefreshMessages } from "../messages/actions";
import { actionError } from "../messages/labels";

type Field = "name" | "phone" | "email" | "company";
type Draft = Record<Field, string>;

function draftOf(card: LeadCard): Draft {
  return {
    name: card.name,
    phone: card.contacts.phone ?? "",
    email: card.contacts.email ?? "",
    company: card.contacts.company ?? "",
  };
}

/** Поле формы, на которое указал отказ BFF (`details.fields`). */
function failedField(error: unknown): Field | null {
  if (!(error instanceof ApiError)) return null;
  const fields = error.details["fields"];
  const first = Array.isArray(fields) ? (fields[0] as unknown) : null;
  return first === "name" || first === "phone" || first === "email" || first === "company"
    ? first
    : null;
}

/** Предупреждение о дубле: другой лид или клиент с тем же номером или почтой — правка уже сохранена. */
function DuplicateNote({ duplicates }: { duplicates: LeadDuplicate[] }) {
  const { t } = useTranslation("leads");
  return (
    <Alert
      type="warning"
      showIcon
      role="status"
      message={t("edit.duplicates")}
      description={
        <ul className="pf-crm-duplicates">
          {duplicates.map((d) => (
            <li key={`${d.kind}-${d.lead ?? String(d.client_id ?? "")}-${d.field}`}>
              {d.lead || d.client_id ? (
                <LinkButton
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  to={
                    d.lead ? `/crm/leads?lead=${d.lead}&panel=open` : clientPath(d.client_id ?? 0)
                  }
                >
                  {d.name || d.lead}
                </LinkButton>
              ) : null}{" "}
              <span className="pf-hint">
                {t(`edit.duplicateKinds.${d.kind}`)} · {t(`edit.fields.${d.field}`)}
              </span>
            </li>
          ))}
        </ul>
      }
    />
  );
}

/**
 * Контакты лида с правкой на месте (LH-1): «Изменить» раскрывает имя, телефон, почту и компанию; сохраняются только
 * изменённые поля. Номер и почту нормализует CRM; другой лид или клиент с тем же номером — предупреждение под блоком.
 * Telegram не правится — его даёт сам клиент.
 */
export function ContactsBlock({ card, canEdit }: { card: LeadCard; canEdit: boolean }) {
  const { t } = useTranslation(["leads", "messages"]);
  const refresh = useRefreshMessages();
  const ids = { name: useId(), phone: useId(), email: useId(), company: useId() };
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => draftOf(card));
  const [duplicates, setDuplicates] = useState<LeadDuplicate[]>([]);
  const [bad, setBad] = useState<Field | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const save = useUpdateCrmLead({
    mutation: {
      onSuccess: (result) => {
        setDuplicates(result.duplicates);
        setEditing(false);
        refresh();
      },
      onError: (error) => {
        setBad(failedField(error));
        setFailure(actionError(t, error));
      },
    },
  });
  const rows = [
    {
      label: t("messages:card.telegram"),
      value: card.contacts.telegram ? `@${card.contacts.telegram}` : "",
    },
    { label: t("messages:card.phone"), value: card.contacts.phone ?? "" },
    { label: t("messages:card.email"), value: card.contacts.email ?? "" },
    { label: t("messages:card.company"), value: card.contacts.company ?? "" },
  ].filter((row) => row.value);
  const start = () => {
    setDraft(draftOf(card));
    setFailure(null);
    setBad(null);
    setDuplicates([]);
    setEditing(true);
  };
  const submit = () => {
    const before = draftOf(card);
    const data: Partial<Record<Field, string>> = {};
    for (const field of ["name", "phone", "email", "company"] as const) {
      if (draft[field].trim() !== before[field]) data[field] = draft[field].trim();
    }
    if (!draft.name.trim()) {
      setBad("name");
      setFailure(t("leads:edit.nameRequired"));
      return;
    }
    if (Object.keys(data).length === 0) {
      setEditing(false);
      return;
    }
    setFailure(null);
    setBad(null);
    save.mutate({ lead: card.lead, data });
  };
  const input = (field: Field, label: string, type?: string) => (
    <FormField id={ids[field]} label={label}>
      <Input
        id={ids[field]}
        type={type}
        status={bad === field ? "error" : undefined}
        maxLength={field === "phone" ? 40 : 255}
        value={draft[field]}
        onChange={(event) => {
          setDraft({ ...draft, [field]: event.target.value });
        }}
      />
    </FormField>
  );
  return (
    <div className="pf-fp-block">
      <div className="pf-fp-row" style={{ alignItems: "center", justifyContent: "space-between" }}>
        <h4>{t("leads:card.contacts")}</h4>
        {canEdit && !editing ? (
          <Button size="small" onClick={start} aria-label={`${t("leads:edit.open")}: ${card.name}`}>
            {t("leads:edit.open")}
          </Button>
        ) : null}
      </div>
      {editing ? (
        <div className="pf-fp-stack">
          {input("name", t("leads:edit.fields.name"))}
          {input("phone", t("leads:edit.fields.phone"), "tel")}
          {input("email", t("leads:edit.fields.email"), "email")}
          {input("company", t("leads:edit.fields.company"))}
          <ErrorNote message={failure} />
          <div className="pf-fp-row">
            <Button
              onClick={() => {
                setEditing(false);
              }}
            >
              {t("leads:edit.cancel")}
            </Button>
            <Button type="primary" loading={save.isPending} onClick={submit}>
              {t("leads:edit.save")}
            </Button>
          </div>
        </div>
      ) : rows.length ? (
        <DefinitionList items={rows} />
      ) : (
        <p className="pf-fp-sub">{t("leads:card.none")}</p>
      )}
      {editing ? null : <EmailProblem problem={card.email_problem} />}
      {duplicates.length ? <DuplicateNote duplicates={duplicates} /> : null}
    </div>
  );
}
