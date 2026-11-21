import { Alert, Button, Checkbox, Input, Radio, Select, Skeleton, Space } from "antd";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
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
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import {
  type RemainingItem,
  StepRemaining,
  StepSections,
} from "../../../shared/ui/StepSections/StepSections";
import { useLeftSteps } from "../../../shared/ui/StepSections/useLeftSteps";
import { reasonError } from "../common/errors";
import { clientPath, useRefreshCrm } from "../common/params";
import { noteLanguage, useCallNote } from "./callNote";
import {
  clearRequestDraft,
  REQUEST_SECTIONS,
  type RequestDraft,
  readRequestDraft,
  requestDraftScope,
  writeRequestDraft,
} from "./draft";
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

type SectionKey = "client" | "contact" | "request" | "review";

/** Поле с ошибкой → его секция (форма секциями, platform-frontend.md §4.1a) */
const SECTION_OF: Record<keyof RequestErrors, SectionKey> = {
  company: "client",
  inn: "client",
  contact: "contact",
  channel: "contact",
  summary: "request",
  letter: "request",
  // Согласие — там же, где вводятся персональные данные клиента
  consent: "contact",
};

const FIELD_ORDER: readonly (keyof RequestErrors)[] = [
  "company",
  "inn",
  "contact",
  "channel",
  "consent",
  "summary",
  "letter",
];

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
  /** Файл письма уже в EDS («Передать в работу» из входящего, план 1.9): форма получает готовое письмо */
  letterFile?: { id: string; name: string } | null;
  /** Заявка создана — вызывающий связывает её со своим объектом (поручение по ВХ) */
  onCreated?: (result: RequestCreatedView) => void;
  onCancel: () => void;
}

/**
 * «+ Создать заявку» (SPEC-v3 §3.1 шаг 2): клиент (выбрать или новая компания с ИНН), контакт хотя бы с одним каналом,
 * суть запроса, письмо на имя директора (файл — в EDS до отправки формы), срочность, согласие на данные. Ключ формы —
 * один на открытие: повтор после сбоя или двойной клик не создаёт вторую заявку (CRM вернёт ту же). Ошибка оставляет
 * введённое; на телефоне форма — лист на весь экран с кнопками внизу.
 */
export function RequestForm({
  lead,
  clientId,
  letterFrom = null,
  letterFile = null,
  onCreated,
  onCancel,
}: RequestFormProps) {
  const { t, i18n } = useTranslation(["request", "clients"]);
  const { me } = useAuth();
  const { mobile } = useViewport();
  const fmt = useFormat();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;
  const [requestKey, setRequestKey] = useState(newKey);
  const [state, setState] = useState<RequestFormState>(() => ({
    ...initialState(lead, clientId),
    ...(letterFrom && lead ? { letter: { name: "", status: "uploading" as const } } : {}),
    ...(letterFile
      ? { letter: { name: letterFile.name, status: "done" as const, id: letterFile.id } }
      : {}),
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
  const [active, setActive] = useState<SectionKey>(() =>
    clientId !== null || lead?.client != null ? "contact" : "client",
  );
  // Шаги, которые человек уже покидал: требования и ошибки полей показываются на них, а не на только что открытом шаге.
  const { left, markLeft } = useLeftSteps(active);
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

  // Черновик: предлагается кнопками, а не подставляется молча; пока выбор не сделан, прежний не перезаписывается.
  const userId = me.id;
  const scope = requestDraftScope(lead?.lead ?? null, clientId, letterFile?.id ?? null);
  const [baseline] = useState(() => initialState(lead, clientId));
  const [offer, setOffer] = useState<RequestDraft | null>(() =>
    userId ? readRequestDraft(userId, scope) : null,
  );
  const incomingLetter = Boolean(letterFrom || letterFile);
  useEffect(() => {
    if (!userId || offer || done) return;
    writeRequestDraft(userId, scope, baseline, incomingLetter, {
      state,
      active,
      contactTouched,
      requestKey,
    });
  }, [
    userId,
    scope,
    baseline,
    incomingLetter,
    offer,
    done,
    state,
    active,
    contactTouched,
    requestKey,
  ]);

  const ctx: RequestContext = {
    lead: lead?.lead ?? null,
    leadChannel: lead?.channel ?? null,
    leadTelegram: lead?.channel === "telegram" ? (lead.contacts.telegram ?? null) : null,
    consentGiven: lead === null || lead.consent.given_at !== null,
    contacts,
  };
  // Основание по звонку (СЦ-6): лид со звонка — записка собирается сама при входе на шаг «Запрос», когда согласие уже есть
  // (дано в CRM или отмечено на «Контакте»); без лида (повторный звонок клиента) — по кнопке «Основание — звонок».
  const consentPresent = lead === null || lead.consent.given_at !== null || state.consentMarked;
  const phoneLead = lead !== null && lead.channel === "phone";
  const callBasis = (lead === null || (phoneLead && consentPresent)) && !incomingLetter;
  const caller = contacts.find((c) => c.id === form.contactId);
  const callerName = caller ? caller.name : state.fullName.trim();
  const callNote = useCallNote((letter) => {
    setState((prev) => ({ ...prev, letter }));
  });
  const startCallNote = () => {
    const lang = noteLanguage(i18n.language);
    if (lead) {
      void callNote.start({
        request_key: requestKey,
        lang,
        lead: lead.lead,
        consent: state.consentMarked,
      });
      return;
    }
    void callNote.start({
      request_key: requestKey,
      lang,
      caller: {
        name: callerName,
        company:
          (state.clientId !== null
            ? (state.clientName ?? client.data?.name)
            : state.companyName.trim()) || null,
        phone: (caller ? caller.phone : state.phone.trim()) || null,
        email: (caller ? caller.email : state.email.trim()) || null,
      },
      need: state.summary.trim() || null,
    });
  };
  const autoNote = useRef(false);
  const wantsAutoNote =
    phoneLead && callBasis && !offer && active === "request" && state.letter === null && !done;
  useEffect(() => {
    if (!wantsAutoNote || autoNote.current) return;
    autoNote.current = true;
    startCallNote();
    // Один раз на открытие формы: после «Убрать файл» записка заново сама не собирается (есть кнопка).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantsAutoNote]);

  // Один валидатор на всё: галочка шага, список «Осталось» и отправка. Ошибка у поля видна, когда шаг уже покидали.
  const all = validateRequest(form, ctx);
  const errors: RequestErrors = Object.fromEntries(
    (Object.keys(all) as (keyof RequestErrors)[])
      .filter((field) => left.has(SECTION_OF[field]))
      .map((field) => [field, all[field]]),
  );
  const sectionTitle: Record<SectionKey, string> = {
    client: t("request:client.legend"),
    contact: t("request:contact.legend"),
    request: t("request:sections.request"),
    review: t("request:sections.review"),
  };
  const needs = (key: SectionKey): string[] =>
    FIELD_ORDER.filter((field) => all[field] && SECTION_OF[field] === key).map((field) =>
      t(`request:errors.${all[field] ?? field}`),
    );
  const remaining: RemainingItem[] = FIELD_ORDER.filter((field) => all[field]).map((field) => ({
    step: SECTION_OF[field],
    title: sectionTitle[SECTION_OF[field]],
    text: t(`request:errors.${all[field] ?? field}`),
  }));
  const err = (field: keyof RequestErrors) =>
    errors[field] ? t(`request:errors.${errors[field]}`) : undefined;
  const set = (change: Partial<RequestFormState>) => {
    setState((prev) => ({ ...prev, ...change }));
  };
  const clientSummary =
    state.clientId !== null
      ? (state.clientName ?? client.data?.name ?? "")
      : [state.companyName.trim(), state.inn.trim()].filter(Boolean).join(" · ");
  const picked = contacts.find((c) => c.id === form.contactId);
  const contactSummary = picked
    ? contactLabel(picked, t)
    : [state.fullName.trim(), state.phone.trim() || state.email.trim()].filter(Boolean).join(" · ");
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

  const cancel = () => {
    if (userId) clearRequestDraft(userId, scope);
    onCancel();
  };

  const submit = () => {
    if (create.isPending) return;
    setServerError(null);
    // Главная кнопка при незаполненном недоступна; Enter в поле ведёт на «Проверку» со списком «Осталось», а не на пройденный шаг
    if (remaining.length > 0) {
      setActive("review");
      return;
    }
    create.mutate(
      { data: toRequestPayload(form, ctx, requestKey) },
      {
        onSuccess: (result) => {
          if (userId) clearRequestDraft(userId, scope);
          refresh();
          setDone(result);
          onCreated?.(result);
        },
        onError: (error) => {
          setServerError(reasonError(t, "request:errors", error));
        },
      },
    );
  };

  const leadTelegram = ctx.leadTelegram;

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

      {offer ? (
        <Alert
          type="info"
          showIcon
          role="status"
          message={t("request:draft.found", { time: fmt.date(offer.savedAt, "datetime") })}
          description={
            <Space wrap>
              <Button
                type="primary"
                size="small"
                onClick={() => {
                  setState((prev) => ({
                    ...offer.state,
                    letter: incomingLetter ? prev.letter : offer.state.letter,
                  }));
                  setContactTouched(offer.contactTouched);
                  setRequestKey(offer.requestKey);
                  markLeft(REQUEST_SECTIONS.slice(0, REQUEST_SECTIONS.indexOf(offer.active)));
                  setActive(offer.active);
                  setOffer(null);
                }}
              >
                {t("request:draft.continue")}
              </Button>
              <Button
                size="small"
                onClick={() => {
                  if (userId) clearRequestDraft(userId, scope);
                  setOffer(null);
                }}
              >
                {t("request:draft.restart")}
              </Button>
            </Space>
          }
        />
      ) : null}

      <StepSections
        headingLevel={4}
        active={active}
        onActiveChange={(key) => {
          setActive(key as SectionKey);
        }}
        sections={[
          {
            key: "client",
            title: t("request:client.legend"),
            summary: clientSummary,
            complete: true,
            requirements: needs("client"),
            showRequirements: left.has("client"),
            content: (
              <div className="pf-fp-stack">
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
              </div>
            ),
          },
          {
            key: "contact",
            title: t("request:contact.legend"),
            summary: contactSummary,
            complete: true,
            requirements: needs("contact"),
            showRequirements: left.has("contact"),
            content: (
              <div className="pf-fp-stack">
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
                                <FormField
                                  id={id("consent-method")}
                                  label={t("request:consent.method")}
                                >
                                  <Select
                                    id={id("consent-method")}
                                    value={state.consentMethod}
                                    options={(["phone", "email", "paper"] as const).map(
                                      (value) => ({
                                        value,
                                        label: t(`request:consent.methods.${value}`),
                                      }),
                                    )}
                                    onChange={(value) => {
                                      set({ consentMethod: value });
                                    }}
                                  />
                                </FormField>
                                <FormField
                                  id={id("consent-comment")}
                                  label={t("request:consent.comment")}
                                >
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
              </div>
            ),
          },
          {
            key: "request",
            title: t("request:sections.request"),
            summary: state.summary.trim().slice(0, 80),
            complete: true,
            requirements: needs("request"),
            showRequirements: left.has("request"),
            content: (
              <div className="pf-fp-stack">
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
                    callNote={
                      callBasis
                        ? {
                            onStart: startCallNote,
                            blockedReason:
                              callerName || lead ? null : t("request:letter.noteNeedsCaller"),
                          }
                        : undefined
                    }
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
              </div>
            ),
          },
          {
            key: "review",
            title: t("request:sections.review"),
            content: (
              <div className="pf-fp-stack">
                <p className="pf-fp-sub">{t("request:clientGets")}</p>
                <StepRemaining
                  id={id("remaining")}
                  items={remaining}
                  onGo={(step) => {
                    setActive(step as SectionKey);
                  }}
                />
                <ErrorNote message={serverError} />

                <div className="pf-crm-actions" data-sheet={mobile}>
                  <Button
                    type="primary"
                    htmlType="submit"
                    loading={create.isPending}
                    disabled={remaining.length > 0}
                    aria-describedby={remaining.length > 0 ? id("remaining") : undefined}
                  >
                    {create.isPending ? t("request:submitting") : t("request:submit")}
                  </Button>
                  <Button onClick={cancel}>{t("request:cancel")}</Button>
                </div>
              </div>
            ),
          },
        ]}
      />
    </form>
  );
}
