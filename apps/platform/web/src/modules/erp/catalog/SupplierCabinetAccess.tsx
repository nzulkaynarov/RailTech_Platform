import { Button, Input, Select, Switch } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import type {
  SupplierCabinetAccess as AccessData,
  SupplierCabinetContact,
  SupplierCabinetContactCreateLanguage,
  SupplierCabinetRelationshipCatalogPriceVisibility,
  SupplierCabinetRelationshipKind,
  SupplierCabinetRelationshipModulesItem,
} from "../../../shared/api/generated/model";
import {
  getGetSupplierCabinetAccessQueryKey,
  useConfirmSupplierCrmClient,
  useRejectSupplierCrmClient,
  useCreateSupplierCabinetContact,
  useGetSupplierCabinetAccess,
  useInviteSupplierToCabinet,
  useSuspendSupplierCabinetAccess,
  useUpdateSupplierCabinetContact,
  useUpdateSupplierCabinetRights,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { ErrorNote, FormField, QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { FormModal } from "./common";
import { catalogErrorText, errorFields } from "./errors";
import { queryLabels } from "./labels";

type Module = SupplierCabinetRelationshipModulesItem;
const LANGUAGES: SupplierCabinetContactCreateLanguage[] = ["ru", "uz", "en"];
const KINDS = ["manufacturer", "supplier", "principal", "other"] as const;

/**
 * Блок «Доступ в кабинет» карточки поставщика (PART-1, ADR-0022): статус отношения «партнёр», роли компании в кабинете,
 * переключатели разделов («Мои товары», «Каталог и заявки»), контакты компании и действия «Пригласить» и «Приостановить».
 * Право решает ERP (`supply.manage`): без него блок только показывает состояние. Эталоны — SAP Business Network и Coupa
 * (права поставщика задаёт покупатель), портал Odoo (доступ по партнёру).
 */
export function SupplierCabinetAccess({ supplierId }: { supplierId: string }) {
  const { t } = useTranslation("catalog");
  const query = useGetSupplierCabinetAccess(supplierId);
  return (
    <section aria-labelledby={`cabinet-${supplierId}`} className="pf-cat-cabinet">
      <h3 className="pf-cat-section" id={`cabinet-${supplierId}`}>
        {t("cabinetAccess.title")}
      </h3>
      <QueryState query={query} labels={queryLabels(t)} level={3} compact>
        {(data) => <AccessBody supplierId={supplierId} data={data} />}
      </QueryState>
    </section>
  );
}

function AccessBody({ supplierId, data }: { supplierId: string; data: AccessData }) {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const dateTime = (value: string) => date(value, "datetime");
  const queryClient = useQueryClient();
  const relationship = data.relationship;
  const editable = data.can_manage;
  // До приглашения переключатели и вид — черновик, он уходит вместе с «Пригласить»; после — правятся сразу.
  const [draftModules, setDraftModules] = useState<Module[]>(data.partner_modules.default);
  const [draftKind, setDraftKind] = useState<SupplierCabinetRelationshipKind>("");
  const [contactForm, setContactForm] = useState<SupplierCabinetContact | "new" | null>(null);
  const [suspending, setSuspending] = useState(false);
  const [inviting, setInviting] = useState<string | null>(null);
  const refresh = (next: AccessData) => {
    queryClient.setQueryData(getGetSupplierCabinetAccessQueryKey(supplierId), next);
  };
  const rights = useUpdateSupplierCabinetRights({ mutation: { onSuccess: refresh } });
  const invite = useInviteSupplierToCabinet({
    mutation: {
      onSuccess: (next) => {
        refresh(next);
        setInviting(null);
      },
      onError: () => {
        setInviting(null);
      },
    },
  });
  const modules: Module[] = relationship ? relationship.modules : draftModules;
  const kind = relationship ? relationship.kind : draftKind;
  const toggle = (module: Module, on: boolean) => {
    const next = data.partner_modules.allowed.filter((m) =>
      m === module ? on : modules.includes(m),
    );
    if (relationship) rights.mutate({ id: supplierId, data: { modules: next } });
    else setDraftModules(next);
  };
  const changeKind = (value: SupplierCabinetRelationshipKind) => {
    if (relationship) rights.mutate({ id: supplierId, data: { kind: value } });
    else setDraftKind(value);
  };
  // Подпись кнопки и её доступное имя начинаются с одного слова (WCAG 2.5.3)
  const inviteLabel = (contact: SupplierCabinetContact) =>
    contact.invited_at || relationship?.status === "suspended"
      ? t("cabinetAccess.inviteAgain")
      : t("cabinetAccess.invite");
  const roles = data.cabinet_roles.map((r) => t(`cabinetAccess.roles.${r}`)).join(" · ");
  const suspended = relationship?.status === "suspended";
  return (
    <div className="pf-cat">
      <div className="pf-cat-actions" aria-live="polite">
        <StatusTag kind="cabinetAccess" status={relationship?.status ?? "none"}>
          {t(`cabinetAccess.status.${relationship?.status ?? "none"}`)}
        </StatusTag>
        <span className="pf-cat-note">
          {roles ? t("cabinetAccess.rolesLine", { roles }) : t("cabinetAccess.closed")}
        </span>
      </div>
      <CrmClientLine
        supplierId={supplierId}
        crmClient={data.crm_client}
        canDecide={editable}
        onDone={refresh}
      />
      {relationship ? (
        <DefinitionList
          items={[
            {
              label: t("cabinetAccess.invitedBy"),
              value: [
                relationship.invited_by?.name,
                relationship.invited_at ? dateTime(relationship.invited_at) : null,
              ]
                .filter(Boolean)
                .join(" · "),
            },
            {
              label: t("cabinetAccess.firstLogin"),
              value: relationship.activated_at
                ? dateTime(relationship.activated_at)
                : t("cabinetAccess.noLogin"),
            },
            ...(suspended && relationship.suspended_at
              ? [
                  {
                    label: t("cabinetAccess.suspendedAt"),
                    value: dateTime(relationship.suspended_at),
                  },
                ]
              : []),
          ]}
        />
      ) : (
        <p className="pf-cat-note">{t("cabinetAccess.notOpened")}</p>
      )}

      <fieldset className="pf-cat-rights" disabled={!editable || rights.isPending}>
        <legend>{t("cabinetAccess.rights")}</legend>
        {data.partner_modules.allowed.map((module) => (
          <ModuleSwitch
            key={module}
            module={module}
            checked={modules.includes(module)}
            disabled={!editable || rights.isPending}
            onChange={(on) => {
              toggle(module, on);
            }}
          />
        ))}
        <KindSelect value={kind} disabled={!editable || rights.isPending} onChange={changeKind} />
        {relationship ? (
          <PriceVisibilitySelect
            value={relationship.catalog_price_visibility}
            disabled={!editable || rights.isPending}
            onChange={(value) => {
              rights.mutate({ id: supplierId, data: { catalog_price_visibility: value } });
            }}
          />
        ) : null}
        <ErrorNote message={rights.error ? catalogErrorText(t, rights.error) : null} />
      </fieldset>

      <h4 className="pf-cat-section">{t("cabinetAccess.contacts")}</h4>
      {data.contacts.length === 0 ? (
        <p className="pf-cat-note">{t("cabinetAccess.noContacts")}</p>
      ) : (
        <ul className="pf-cat-contacts" aria-label={t("cabinetAccess.contactsTable")}>
          {data.contacts.map((contact) => (
            <li key={contact.id} className="pf-cat-contact">
              <div className="pf-cat-contact-info">
                <strong>{contact.name}</strong>
                <span>{contact.email}</span>
                {contact.phone ? <span className="pf-cat-sub">{contact.phone}</span> : null}
                <span className="pf-cat-sub">
                  {t(`cabinetAccess.languages.${contact.language}`)}
                  {" · "}
                  {contact.last_login_at
                    ? t("cabinetAccess.contact.lastLoginAt", {
                        date: dateTime(contact.last_login_at),
                      })
                    : contact.invited_at
                      ? t("cabinetAccess.contact.invitedAt", { date: dateTime(contact.invited_at) })
                      : t("cabinetAccess.contact.notInvited")}
                </span>
              </div>
              <ContactRight supplierId={supplierId} contact={contact} editable={editable} />
              {editable ? (
                <div className="pf-cat-actions">
                  <Button
                    size="small"
                    aria-label={t("cabinetAccess.contact.editNamed", { name: contact.name })}
                    onClick={() => {
                      setContactForm(contact);
                    }}
                  >
                    {t("cabinetAccess.contact.edit")}
                  </Button>
                  <Button
                    size="small"
                    type="primary"
                    loading={inviting === contact.id}
                    aria-label={t("cabinetAccess.inviteNamed", {
                      action: inviteLabel(contact),
                      name: contact.name,
                    })}
                    onClick={() => {
                      setInviting(contact.id);
                      invite.mutate({
                        id: supplierId,
                        data: {
                          contact_id: contact.id,
                          ...(relationship ? {} : { modules: draftModules, kind: draftKind }),
                        },
                      });
                    }}
                  >
                    {inviteLabel(contact)}
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      <ErrorNote message={invite.error ? catalogErrorText(t, invite.error) : null} />
      {invite.isSuccess ? (
        <p className="pf-cat-note" role="status">
          {t("cabinetAccess.inviteSent")}
        </p>
      ) : null}
      {editable ? (
        <div className="pf-cat-actions">
          <Button
            onClick={() => {
              setContactForm("new");
            }}
          >
            {t("cabinetAccess.addContact")}
          </Button>
          {relationship && !suspended ? (
            <Button
              danger
              onClick={() => {
                setSuspending(true);
              }}
            >
              {t("cabinetAccess.suspend")}
            </Button>
          ) : null}
        </div>
      ) : (
        <p className="pf-cat-note">{t("cabinetAccess.readOnly")}</p>
      )}
      {contactForm ? (
        <ContactForm
          supplierId={supplierId}
          contact={contactForm === "new" ? undefined : contactForm}
          onClose={() => {
            setContactForm(null);
          }}
        />
      ) : null}
      {suspending ? (
        <SuspendModal
          supplierId={supplierId}
          onDone={(next) => {
            refresh(next);
            setSuspending(false);
          }}
          onClose={() => {
            setSuspending(false);
          }}
        />
      ) : null}
    </div>
  );
}

function ModuleSwitch({
  module,
  checked,
  disabled,
  onChange,
}: {
  module: Module;
  checked: boolean;
  disabled: boolean;
  onChange: (on: boolean) => void;
}) {
  const { t } = useTranslation("catalog");
  const id = useId();
  return (
    <div className="pf-cat-switch">
      <Switch
        checked={checked}
        disabled={disabled}
        aria-labelledby={`${id}-label`}
        aria-describedby={`${id}-hint`}
        onChange={onChange}
      />
      <div>
        <span id={`${id}-label`}>{t(`cabinetAccess.modules.${module}.label`)}</span>
        <span className="pf-hint pf-cat-sub" id={`${id}-hint`}>
          {t(`cabinetAccess.modules.${module}.hint`)}
        </span>
      </div>
    </div>
  );
}

function KindSelect({
  value,
  disabled,
  onChange,
}: {
  value: SupplierCabinetRelationshipKind;
  disabled: boolean;
  onChange: (value: SupplierCabinetRelationshipKind) => void;
}) {
  const { t } = useTranslation("catalog");
  const id = useId();
  return (
    <FormField id={id} label={t("cabinetAccess.kind.label")} hint={t("cabinetAccess.kind.hint")}>
      <Select
        id={id}
        allowClear
        disabled={disabled}
        value={value || undefined}
        placeholder={t("cabinetAccess.kind.none")}
        onChange={(next: SupplierCabinetRelationshipKind | undefined) => {
          onChange(next ?? "");
        }}
        options={KINDS.map((kind) => ({ value: kind, label: t(`cabinetAccess.kind.${kind}`) }))}
      />
    </FormField>
  );
}

/** «Цены товаров в каталоге» (PART-3): как клиенты видят цены товаров партнёра; своя политика карточки сильнее. */
function PriceVisibilitySelect({
  value,
  disabled,
  onChange,
}: {
  value: SupplierCabinetRelationshipCatalogPriceVisibility;
  disabled: boolean;
  onChange: (value: SupplierCabinetRelationshipCatalogPriceVisibility) => void;
}) {
  const { t } = useTranslation("catalog");
  const id = useId();
  return (
    <FormField id={id} label={t("partnerPrice.label")} hint={t("partnerPrice.hint")}>
      <Select
        id={id}
        disabled={disabled}
        value={value}
        aria-describedby={`${id}-hint`}
        onChange={onChange}
        options={[
          { value: "", label: t("partnerPrice.inherit") },
          { value: "cabinet", label: t("partnerPrice.cabinet") },
          { value: "on_request", label: t("partnerPrice.on_request") },
        ]}
      />
    </FormField>
  );
}

function ContactForm({
  supplierId,
  contact,
  onClose,
}: {
  supplierId: string;
  contact?: SupplierCabinetContact;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const [name, setName] = useState(contact?.name ?? "");
  const [email, setEmail] = useState(contact?.email ?? "");
  const [phone, setPhone] = useState(contact?.phone ?? "");
  const [language, setLanguage] = useState<SupplierCabinetContactCreateLanguage>(
    contact?.language ?? "ru",
  );
  const [canAct, setCanAct] = useState(contact?.can_act ?? true);
  const ids = { name: useId(), email: useId(), phone: useId(), language: useId(), canAct: useId() };
  const done = () => {
    void queryClient.invalidateQueries({
      queryKey: getGetSupplierCabinetAccessQueryKey(supplierId),
    });
    onClose();
  };
  const create = useCreateSupplierCabinetContact({ mutation: { onSuccess: done } });
  const update = useUpdateSupplierCabinetContact({ mutation: { onSuccess: done } });
  const mutation = contact ? update : create;
  const fields = errorFields(mutation.error);
  const valid = name.trim() !== "" && /^\S+@\S+\.\S+$/.test(email.trim());
  const submit = () => {
    const data = {
      name: name.trim(),
      email: email.trim(),
      phone: phone.trim(),
      language,
      can_act: canAct,
    };
    if (contact) update.mutate({ id: supplierId, contactId: contact.id, data });
    else create.mutate({ id: supplierId, data });
  };
  return (
    <FormModal
      title={
        contact ? t("cabinetAccess.contactForm.editTitle") : t("cabinetAccess.contactForm.addTitle")
      }
      okLabel={contact ? t("save") : t("cabinetAccess.contactForm.add")}
      items={
        contact ? [] : (t("cabinetAccess.contactForm.steps", { returnObjects: true }) as string[])
      }
      loading={mutation.isPending}
      error={mutation.error}
      disabled={!valid}
      onOk={submit}
      onCancel={onClose}
    >
      <FormField id={ids.name} label={t("cabinetAccess.contact.name")}>
        <Input
          id={ids.name}
          value={name}
          maxLength={255}
          status={fields.includes("name") ? "error" : undefined}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
      </FormField>
      <div className="pf-cat-form-row">
        <FormField
          id={ids.email}
          label={t("cabinetAccess.contact.email")}
          hint={t("cabinetAccess.contactForm.emailHint")}
        >
          <Input
            id={ids.email}
            type="email"
            value={email}
            status={fields.includes("email") ? "error" : undefined}
            onChange={(e) => {
              setEmail(e.target.value);
            }}
          />
        </FormField>
        <FormField id={ids.phone} label={t("cabinetAccess.contact.phone")}>
          <Input
            id={ids.phone}
            type="tel"
            maxLength={50}
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value);
            }}
          />
        </FormField>
      </div>
      <FormField
        id={ids.language}
        label={t("cabinetAccess.contact.language")}
        hint={t("cabinetAccess.contactForm.languageHint")}
      >
        <Select
          id={ids.language}
          value={language}
          onChange={setLanguage}
          options={LANGUAGES.map((l) => ({ value: l, label: t(`cabinetAccess.languages.${l}`) }))}
        />
      </FormField>
      <div className="pf-cat-switch">
        <Switch
          checked={canAct}
          aria-labelledby={`${ids.canAct}-label`}
          onChange={(on) => {
            setCanAct(on);
          }}
        />
        <span id={`${ids.canAct}-label`}>{t("cabinetAccess.contactForm.canAct")}</span>
      </div>
    </FormModal>
  );
}

/** Право контакта действовать: «участник» создаёт запросы и загружает файлы, «просмотр» только читает. Правится сразу. */
function ContactRight({
  supplierId,
  contact,
  editable,
}: {
  supplierId: string;
  contact: SupplierCabinetContact;
  editable: boolean;
}) {
  const { t } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const update = useUpdateSupplierCabinetContact({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getGetSupplierCabinetAccessQueryKey(supplierId),
        });
      },
    },
  });
  return (
    <div className="pf-cat-switch pf-cat-contact-right">
      <Switch
        checked={contact.can_act}
        disabled={!editable || update.isPending}
        aria-label={t("cabinetAccess.contact.canActNamed", { name: contact.name })}
        onChange={(on) => {
          update.mutate({ id: supplierId, contactId: contact.id, data: { can_act: on } });
        }}
      />
      <span aria-hidden="true">{t("cabinetAccess.contact.canAct")}</span>
      <ErrorNote message={update.error ? catalogErrorText(t, update.error) : null} />
    </div>
  );
}

function SuspendModal({
  supplierId,
  onDone,
  onClose,
}: {
  supplierId: string;
  onDone: (next: AccessData) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const suspend = useSuspendSupplierCabinetAccess({ mutation: { onSuccess: onDone } });
  return (
    <FormModal
      title={t("cabinetAccess.suspendForm.title")}
      okLabel={t("cabinetAccess.suspendForm.ok")}
      items={t("cabinetAccess.suspendForm.steps", { returnObjects: true }) as string[]}
      loading={suspend.isPending}
      error={suspend.error}
      onOk={() => {
        suspend.mutate({ id: supplierId });
      }}
      onCancel={onClose}
    >
      <p>{t("cabinetAccess.suspendForm.text")}</p>
    </FormModal>
  );
}

/**
 * «Клиент в CRM» (PART-CRM): приглашённый партнёр становится клиентом CRM — заведён / ожидает / конфликт, и ссылка на
 * карточку клиента. CRM — источник правды по клиентам; конфликт значит «найденный клиент привязан к другой компании ERP».
 */
function CrmClientLine({
  supplierId,
  crmClient,
  canDecide,
  onDone,
}: {
  supplierId: string;
  crmClient: AccessData["crm_client"];
  canDecide: boolean;
  onDone: (next: AccessData) => void;
}) {
  const { t } = useTranslation("catalog");
  const confirm = useConfirmSupplierCrmClient({ mutation: { onSuccess: onDone } });
  const reject = useRejectSupplierCrmClient({ mutation: { onSuccess: onDone } });
  if (crmClient.status === "none") return null;
  if (crmClient.status === "unverified") {
    // Сопоставление создала передача клиента по совпадению ИНН: сотрудник подтверждает, та ли это компания (PART-CRM).
    const busy = confirm.isPending || reject.isPending;
    const error = confirm.error ?? reject.error;
    return (
      <div className="pf-cat-crm-verify" role="group" aria-labelledby={`crm-verify-${supplierId}`}>
        <div className="pf-cat-actions">
          <span className="pf-cat-note">{t("cabinetAccess.crmClient.label")}</span>
          <StatusTag kind="crmClient" status="unverified">
            {t("cabinetAccess.crmClient.unverified")}
          </StatusTag>
        </div>
        <p id={`crm-verify-${supplierId}`} className="pf-cat-note">
          {t("cabinetAccess.crmClient.verify.found", {
            name: crmClient.crm_client_name ?? `№${crmClient.crm_client_id ?? ""}`,
            inn: crmClient.inn ?? "—",
          })}
        </p>
        {crmClient.crm_client_id ? (
          <div className="pf-cat-actions">
            <Link className="pf-focusable" to={`/crm/clients/${crmClient.crm_client_id}`}>
              {t("cabinetAccess.crmClient.open")}
            </Link>
          </div>
        ) : null}
        <p className="pf-cat-note">{t("cabinetAccess.crmClient.verify.question")}</p>
        {canDecide ? (
          <div className="pf-cat-actions">
            <Button
              type="primary"
              loading={confirm.isPending}
              disabled={busy}
              onClick={() => {
                confirm.mutate({ id: supplierId });
              }}
            >
              {t("cabinetAccess.crmClient.verify.yes")}
            </Button>
            <Button
              loading={reject.isPending}
              disabled={busy}
              onClick={() => {
                reject.mutate({ id: supplierId });
              }}
            >
              {t("cabinetAccess.crmClient.verify.no")}
            </Button>
          </div>
        ) : (
          <p className="pf-cat-note">{t("cabinetAccess.crmClient.verify.readOnly")}</p>
        )}
        <ErrorNote message={error ? catalogErrorText(t, error) : null} />
      </div>
    );
  }
  return (
    <div className="pf-cat-actions" aria-live="polite">
      <span className="pf-cat-note">{t("cabinetAccess.crmClient.label")}</span>
      <StatusTag kind="crmClient" status={crmClient.status}>
        {t(`cabinetAccess.crmClient.${crmClient.status}`)}
      </StatusTag>
      {crmClient.crm_client_id ? (
        <Link
          className="pf-focusable"
          to={`/crm/clients/${crmClient.crm_client_id}`}
          aria-label={t("cabinetAccess.crmClient.openNamed", { id: crmClient.crm_client_id })}
        >
          {t("cabinetAccess.crmClient.open")}
        </Link>
      ) : null}
      <span className="pf-cat-note">{t(`cabinetAccess.crmClient.hint.${crmClient.status}`)}</span>
    </div>
  );
}
