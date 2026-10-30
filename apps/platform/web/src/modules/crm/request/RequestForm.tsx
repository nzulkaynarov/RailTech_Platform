import { Button, Checkbox, Input, Radio, Select, Skeleton } from "antd";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import type {
  ClientContactView,
  LeadCard,
  RequestCreatedView,
} from "../../../shared/api/generated/model";
import {
  useCopyCrmMessageAttachmentToRequest,
  useCreateCrmRequest,
  useGetCrmClient,
  useListCrmClients,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { reasonError } from "../common/errors";
import { clientPath, useRefreshCrm } from "../common/params";
import {
  type RequestContext,
  type RequestErrors,
  type RequestFormState,
  emptyRequestForm,
  toRequestPayload,
  validateRequest,
} from "./formModel";
import { LetterField } from "./LetterField";

import "../crm.css";

function newKey(): string {
  return crypto.randomUUID();
}

/** Начальные значения из лида: компания и контакты из переписки, суть — запрос, который собрал бот. */
function initialState(lead: LeadCard | null, clientId: number | null): RequestFormState {
  const state = emptyRequestForm();
  const fixed = clientId ?? lead?.client?.id ?? null;
  if (fixed !== null) {
    state.clientId = fixed;
    state.clientName = lead?.client?.name ?? null;
  }
  if (!lead) return state;
  state.companyName = lead.facts.company ?? lead.contacts.company ?? "";
  state.fullName = lead.name;
  state.phone = lead.contacts.phone ?? "";
  state.email = lead.contacts.email ?? "";
  state.useLeadTelegram = lead.channel === "telegram" && Boolean(lead.contacts.telegram);
  state.summary = lead.need ?? "";
  return state;
}

function FieldError({ id, text }: { id: string; text: string | undefined }) {
  if (!text) return null;
  return (
    <span id={id} className="pf-req-error" role="alert">
      {text}
    </span>
  );
}

function contactLabel(contact: ClientContactView, t: (key: string) => string): string {
  const channels = contact.channels.map((c) => t(`clients:card.channels.${c}`)).join(", ");
  return `${contact.name}${contact.position ? `, ${contact.position}` : ""} — ${channels || t("clients:card.noChannels")}`;
}

/** Поиск клиента по названию компании: подсказка «Выбрать: …», чтобы лид не завёл дубль компании. */
function ClientMatches({
  name,
  onPick,
}: {
  name: string;
  onPick: (id: number, name: string) => void;
}) {
  const { t } = useTranslation("request");
  const q = name.trim();
  const list = useListCrmClients({ q }, { query: { enabled: q.length >= 3 } });
  const items = q.length >= 3 ? (list.data?.items ?? []).slice(0, 3) : [];
  if (items.length === 0) return null;
  return (
    <div className="pf-fp-row" role="group" aria-label={t("client.searchHint")}>
      {items.map((client) => (
        <Button
          key={client.id}
          size="small"
          onClick={() => {
            onPick(client.id, client.name);
          }}
        >
          {t("client.pick", { name: client.inn ? `${client.name} (${client.inn})` : client.name })}
        </Button>
      ))}
    </div>
  );
}

/** Вложение сообщения лида, которое станет письмом директору */
export interface LetterSource {
  message: number;
  index: number;
}

export interface RequestFormProps {
  /** Карточка лида, из которого создаётся заявка; `null` — форма из карточки клиента */
  lead: LeadCard | null;
  /** Клиент, для которого создаётся заявка (карточка клиента) */
  clientId: number | null;
  /** «В заявку» у файла клиента: BFF копирует вложение в EDS, форма получает готовое письмо */
  letterFrom?: LetterSource | null;
  onCancel: () => void;
}

/**
 * «+ Создать заявку» (SPEC-v3 §3.1 шаг 2): клиент (выбрать или новая компания с ИНН), контакт хотя бы с одним каналом,
 * суть запроса, письмо на имя директора (файл — в EDS до отправки формы), срочность, согласие на данные. Ключ формы —
 * один на открытие: повтор после сбоя или двойной клик не создаёт вторую заявку (CRM вернёт ту же). Ошибка оставляет
 * введённое; на телефоне форма — лист на весь экран с кнопками внизу.
 */
export function RequestForm({ lead, clientId, letterFrom = null, onCancel }: RequestFormProps) {
  const { t } = useTranslation(["request", "clients"]);
  const { mobile } = useViewport();
  const fmt = useFormat();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;
  const [requestKey] = useState(newKey);
  const [state, setState] = useState<RequestFormState>(() => ({
    ...initialState(lead, clientId),
    ...(letterFrom && lead ? { letter: { name: "", status: "uploading" as const } } : {}),
  }));
  const copy = useCopyCrmMessageAttachmentToRequest();
  const copied = useRef(false);
  // Вложение из переписки копируется в EDS один раз на открытие формы (повторный эффект StrictMode — не второй файл).
  useEffect(() => {
    if (!letterFrom || !lead || copied.current) return;
    copied.current = true;
    copy
      .mutateAsync({
        data: { lead: lead.lead, message: letterFrom.message, index: letterFrom.index },
      })
      .then((file) => {
        setState((prev) => ({ ...prev, letter: { name: file.name, status: "done", id: file.id } }));
      })
      .catch((error: unknown) => {
        setState((prev) => ({
          ...prev,
          letter: {
            name: "",
            status: "error",
            error: t("request:letter.failed", { reason: reasonError(t, "request:errors", error) }),
          },
        }));
      });
  }, [letterFrom, lead, copy, t]);
  const [tried, setTried] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [done, setDone] = useState<RequestCreatedView | null>(null);
  const create = useCreateCrmRequest();
  const refresh = useRefreshCrm();
  const fixedClient = clientId !== null || lead?.client != null;

  const client = useGetCrmClient(state.clientId ?? 0, {
    query: { enabled: state.clientId !== null },
  });
  const contacts = state.clientId !== null ? (client.data?.contacts ?? []) : [];
  // Пока сотрудник не выбрал контакт сам — основной контакт клиента (Telegram лида уже привязан к нему).
  const [contactTouched, setContactTouched] = useState(false);
  const primary = contacts.find((c) => c.is_primary) ?? contacts[0];
  const form: RequestFormState = contactTouched
    ? state
    : { ...state, contactId: primary ? primary.id : null };

  const ctx: RequestContext = {
    lead: lead?.lead ?? null,
    leadChannel: lead?.channel ?? null,
    leadTelegram: lead?.channel === "telegram" ? (lead.contacts.telegram ?? null) : null,
    consentGiven: lead === null || lead.consent.given_at !== null,
    contacts,
  };
  const errors: RequestErrors = tried ? validateRequest(form, ctx) : {};
  const err = (field: keyof RequestErrors) =>
    errors[field] ? t(`request:errors.${errors[field]}`) : undefined;
  const set = (change: Partial<RequestFormState>) => {
    setState((prev) => ({ ...prev, ...change }));
  };
  const describedBy = (field: keyof RequestErrors, hint = false) =>
    [hint ? `${id(field)}-hint` : null, errors[field] ? `${id(field)}-error` : null]
      .filter(Boolean)
      .join(" ") || undefined;

  if (done) {
    return (
      <div className="pf-fp-stack" role="status">
        <h3 className="pf-fp-title">{t("request:done.title")}</h3>
        <p className="pf-fp-sub">
          {done.created ? t("request:done.text") : t("request:done.repeated")}
        </p>
        <div className="pf-crm-actions" data-sheet={mobile}>
          <LinkButton type="primary" to={clientPath(done.client_id)}>
            {t("request:done.openClient")}
          </LinkButton>
          <Button onClick={onCancel}>{t("clients:card.close")}</Button>
        </div>
      </div>
    );
  }

  const submit = () => {
    if (create.isPending) return;
    setTried(true);
    setServerError(null);
    if (Object.keys(validateRequest(form, ctx)).length > 0) return;
    if (state.letter?.status === "uploading") return;
    create.mutate(
      { data: toRequestPayload(form, ctx, requestKey) },
      {
        onSuccess: (result) => {
          refresh();
          setDone(result);
        },
        onError: (error) => {
          setServerError(reasonError(t, "request:errors", error));
        },
      },
    );
  };

  const leadTelegram = ctx.leadTelegram;
  const consequence = [
    ...(lead && !lead.client ? [t("request:consequence.lead")] : []),
    t("request:consequence.request"),
    ...(state.letter?.status === "done"
      ? [
          t("request:consequence.letter", {
            urgent: state.urgency === "urgent" ? t("request:consequence.urgentSuffix") : "",
          }),
        ]
      : []),
    t("request:consequence.chat"),
  ];

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
      <div className="pf-fp-stack" style={{ gap: 4 }}>
        {/* На телефоне заголовок листа уже «Создать заявку» — второй виден только скринридеру */}
        <h3 className={mobile ? "pf-sr-only" : "pf-fp-title"} id={id("title")}>
          {t("request:title")}
        </h3>
        {lead ? <p className="pf-fp-sub">{t("request:from", { lead: lead.lead })}</p> : null}
        <p className="pf-fp-sub">{t("request:intro")}</p>
      </div>

      <fieldset className="pf-req-group">
        <legend>{t("request:client.legend")}</legend>
        {state.clientId !== null ? (
          <div className="pf-fp-row" style={{ alignItems: "center" }}>
            <span>
              {t("request:client.picked", {
                name: state.clientName ?? client.data?.name ?? `#${String(state.clientId)}`,
              })}
            </span>
            {fixedClient ? null : (
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => {
                  setContactTouched(false);
                  set({ clientId: null, clientName: null, contactId: null });
                }}
              >
                {t("request:client.change")}
              </Button>
            )}
          </div>
        ) : (
          <>
            <FormField id={id("company")} label={t("request:client.name")}>
              <Input
                id={id("company")}
                value={state.companyName}
                maxLength={255}
                aria-invalid={errors.company ? true : undefined}
                aria-describedby={describedBy("company")}
                onChange={(event) => {
                  set({ companyName: event.target.value });
                }}
              />
              <FieldError id={`${id("company")}-error`} text={err("company")} />
            </FormField>
            <ClientMatches
              name={state.companyName}
              onPick={(picked, name) => {
                setContactTouched(false);
                set({ clientId: picked, clientName: name, contactId: null });
              }}
            />
            <FormField
              id={id("inn")}
              label={t("request:client.inn")}
              hint={t("request:client.innHint")}
            >
              <Input
                id={id("inn")}
                value={state.inn}
                inputMode="numeric"
                maxLength={14}
                aria-invalid={errors.inn ? true : undefined}
                aria-describedby={describedBy("inn", true)}
                onChange={(event) => {
                  set({ inn: event.target.value });
                }}
              />
              <FieldError id={`${id("inn")}-error`} text={err("inn")} />
            </FormField>
          </>
        )}
      </fieldset>

      <fieldset className="pf-req-group">
        <legend>{t("request:contact.legend")}</legend>
        {state.clientId !== null && client.isPending ? (
          <Skeleton active paragraph={{ rows: 1 }} title={false} />
        ) : null}
        {contacts.length > 0 ? (
          <FormField id={id("contact-pick")} label={t("request:contact.existing")}>
            <Select
              id={id("contact-pick")}
              value={form.contactId ?? 0}
              options={[
                ...contacts.map((c) => ({ value: c.id, label: contactLabel(c, t) })),
                { value: 0, label: t("request:contact.newContact") },
              ]}
              onChange={(value: number) => {
                setContactTouched(true);
                set({ contactId: value === 0 ? null : value });
              }}
            />
          </FormField>
        ) : null}
        {form.contactId === null ? (
          <>
            <FormField id={id("contact")} label={t("request:contact.name")}>
              <Input
                id={id("contact")}
                value={state.fullName}
                maxLength={255}
                aria-invalid={errors.contact ? true : undefined}
                aria-describedby={describedBy("contact")}
                onChange={(event) => {
                  set({ fullName: event.target.value });
                }}
              />
              <FieldError id={`${id("contact")}-error`} text={err("contact")} />
            </FormField>
            <FormField id={id("position")} label={t("request:contact.position")}>
              <Input
                id={id("position")}
                value={state.position}
                maxLength={255}
                onChange={(event) => {
                  set({ position: event.target.value });
                }}
              />
            </FormField>
            <p className="pf-hint" id={`${id("channel")}-hint`}>
              {t("request:contact.channelsHint")}
            </p>
            {leadTelegram ? (
              <Checkbox
                checked={state.useLeadTelegram}
                onChange={(event) => {
                  set({ useLeadTelegram: event.target.checked });
                }}
              >
                {t("request:contact.telegram", { username: `@${leadTelegram}` })}
              </Checkbox>
            ) : null}
            <FormField id={id("phone")} label={t("request:contact.phone")}>
              <Input
                id={id("phone")}
                value={state.phone}
                type="tel"
                maxLength={32}
                aria-invalid={errors.channel ? true : undefined}
                aria-describedby={describedBy("channel", true)}
                onChange={(event) => {
                  set({ phone: event.target.value });
                }}
              />
            </FormField>
            <FormField id={id("email")} label={t("request:contact.email")}>
              <Input
                id={id("email")}
                value={state.email}
                type="email"
                maxLength={255}
                aria-invalid={errors.channel ? true : undefined}
                aria-describedby={describedBy("channel", true)}
                onChange={(event) => {
                  set({ email: event.target.value });
                }}
              />
            </FormField>
          </>
        ) : null}
        <FieldError id={`${id("channel")}-error`} text={err("channel")} />
      </fieldset>

      <FormField
        id={id("summary")}
        label={t("request:summary.label")}
        hint={t("request:summary.hint")}
      >
        <Input.TextArea
          id={id("summary")}
          value={state.summary}
          maxLength={5000}
          autoSize={{ minRows: 3, maxRows: 8 }}
          aria-invalid={errors.summary ? true : undefined}
          aria-describedby={describedBy("summary", true)}
          onChange={(event) => {
            set({ summary: event.target.value });
          }}
        />
        <FieldError id={`${id("summary")}-error`} text={err("summary")} />
      </FormField>

      <FormField
        id={id("letter")}
        label={t("request:letter.label")}
        hint={t("request:letter.hint")}
      >
        <LetterField
          id={id("letter")}
          value={state.letter}
          onChange={(letter) => {
            set({ letter });
          }}
        />
        <FieldError id={`${id("letter")}-error`} text={err("letter")} />
      </FormField>

      <fieldset className="pf-req-group">
        <legend>{t("request:urgency.legend")}</legend>
        <Radio.Group
          value={state.urgency}
          onChange={(event) => {
            set({ urgency: event.target.value as RequestFormState["urgency"] });
          }}
          options={[
            { value: "normal", label: t("request:urgency.normal") },
            { value: "urgent", label: t("request:urgency.urgent") },
          ]}
        />
      </fieldset>

      {lead ? (
        <fieldset className="pf-req-group">
          <legend>{t("request:consent.legend")}</legend>
          {lead.consent.given_at ? (
            <p className="pf-fp-sub">
              {t(
                lead.consent.method === null
                  ? "request:consent.given"
                  : "request:consent.givenStaff",
                {
                  date: fmt.date(lead.consent.given_at),
                },
              )}
            </p>
          ) : (
            <>
              <p className="pf-fp-sub">{t("request:consent.missing")}</p>
              {lead.channel === "telegram" ? (
                <p className="pf-fp-sub">{t("request:consent.viaBot")}</p>
              ) : (
                <>
                  <Checkbox
                    checked={state.consentMarked}
                    aria-invalid={errors.consent ? true : undefined}
                    onChange={(event) => {
                      set({ consentMarked: event.target.checked });
                    }}
                  >
                    {t("request:consent.mark")}
                  </Checkbox>
                  {state.consentMarked ? (
                    <>
                      <FormField id={id("consent-method")} label={t("request:consent.method")}>
                        <Select
                          id={id("consent-method")}
                          value={state.consentMethod}
                          options={(["phone", "email", "paper"] as const).map((value) => ({
                            value,
                            label: t(`request:consent.methods.${value}`),
                          }))}
                          onChange={(value) => {
                            set({ consentMethod: value });
                          }}
                        />
                      </FormField>
                      <FormField id={id("consent-comment")} label={t("request:consent.comment")}>
                        <Input
                          id={id("consent-comment")}
                          value={state.consentComment}
                          maxLength={500}
                          onChange={(event) => {
                            set({ consentComment: event.target.value });
                          }}
                        />
                      </FormField>
                    </>
                  ) : null}
                </>
              )}
            </>
          )}
          <FieldError id={`${id("consent")}-error`} text={err("consent")} />
        </fieldset>
      ) : null}

      <Consequence items={consequence} />
      <p className="pf-fp-sub">{t("request:clientGets")}</p>
      <ErrorNote message={serverError} />

      <div className="pf-crm-actions" data-sheet={mobile}>
        <Button
          type="primary"
          htmlType="submit"
          loading={create.isPending}
          disabled={state.letter?.status === "uploading"}
        >
          {create.isPending ? t("request:submitting") : t("request:submit")}
        </Button>
        <Button onClick={onCancel}>{t("request:cancel")}</Button>
      </div>
    </form>
  );
}
