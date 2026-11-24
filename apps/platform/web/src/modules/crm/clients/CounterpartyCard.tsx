import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Input, Skeleton, Tabs, Tag } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type {
  CounterpartyCard as Card,
  CounterpartyRoleInRole,
} from "../../../shared/api/generated/model";
import {
  getGetCounterpartyByClientQueryKey,
  getGetCounterpartyQueryKey,
  getListCatalogSuppliersQueryKey,
  getListCrmClientsQueryKey,
  useGetCounterparty,
  useGetCounterpartyByClient,
  useClearCounterpartyDoNotWork,
  useSetCounterpartyDoNotWork,
  useSetCounterpartyRole,
  useUpdateCounterpartyRequisites,
} from "../../../shared/api/generated/platform-bff";
import { companyToday } from "../../../shared/lib/dates";
import { DateField } from "../../../shared/ui/DateField";
import { Dialog } from "../../../shared/ui/Dialog";
import { DoNotWorkStrip } from "../../../shared/ui/DoNotWorkStrip";
import { PersonCell } from "../../../shared/ui/EntityCell";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { FormSheet } from "../../../shared/ui/FormSheet";
import { PartnerCard } from "../../erp/catalog/PartnerCard";
import { ClientPanel } from "./ClientPanel";

import "./counterparty.css";

type Part = "overview" | "client" | "supplier";
const EDITABLE: readonly CounterpartyRoleInRole[] = ["supplier", "manufacturer"];
const ROLE_ORDER = ["client", "supplier", "manufacturer", "partner", "organization"] as const;

/**
 * Карточка контрагента — одна компания во всех ролях (ADR-0028, СУЩ-2.5; макет «Контрагент», лист 2). Открывается и по
 * клиенту CRM (`?client=`), и по компании ERP (`?partner=`): шапка, роли-отметки и «Обзор» (люди, счета, бренды) общие,
 * «Заявки и проекты» и «Товары поставщика» — вкладки той же карточки. Клиент CRM, которого ещё нет в ERP, показывается
 * прежней карточкой клиента: компании, к которой относятся роли, пока нет.
 */
export function CounterpartyCard({
  clientId,
  companyId,
  onClose,
}: {
  clientId?: number | null;
  companyId?: string | null;
  onClose: () => void;
}) {
  const byCompany = useGetCounterparty(companyId ?? "", {
    query: { enabled: Boolean(companyId), retry: false },
  });
  const byClient = useGetCounterpartyByClient(String(clientId ?? ""), {
    query: { enabled: !companyId && clientId != null, retry: false },
  });
  const query = companyId ? byCompany : byClient;

  if (query.isPending) return <Skeleton active paragraph={{ rows: 6 }} title={false} />;
  if (query.isError) {
    // Клиент CRM ещё не передан в ERP (или сотруднику компании ERP не видны): карточка клиента как есть
    if (clientId != null) return <ClientPanel id={clientId} onClose={onClose} />;
    if (companyId) return <PartnerCard id={companyId} />;
    return null;
  }
  return (
    <Loaded
      card={query.data}
      clientId={clientId ?? query.data.crm_client_id}
      entry={companyId ? "supplier" : "client"}
      onClose={onClose}
    />
  );
}

function Loaded({
  card,
  clientId,
  entry,
  onClose,
}: {
  card: Card;
  clientId: number | null;
  entry: Part;
  onClose: () => void;
}) {
  const { t } = useTranslation("clients");
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const seesClients = canSee(me, { resource: "crm.clients" });
  const seesStock = canSee(me, { resource: "erp.stock" });
  const editable = canEdit(me, "erp.stock");
  // СУЩ-2.7: реквизиты ведёт ERP — правит менеджер клиентов или снабжение (в ERP — право роли)
  const requisitesEditable = canEdit(me, "crm.clients") || editable;
  const [editing, setEditing] = useState(false);
  const [marking, setMarking] = useState(false);
  const hasClient = seesClients && clientId !== null;
  const hasSupplier = seesStock && (card.roles.supplier || card.roles.manufacturer);
  const first: Part =
    entry === "client" && hasClient
      ? "client"
      : entry === "supplier" && hasSupplier
        ? "supplier"
        : "overview";
  const [part, setPart] = useState<Part>(first);

  const store = (next: Card) => {
    queryClient.setQueryData(getGetCounterpartyQueryKey(card.id), next);
    if (clientId !== null) {
      queryClient.setQueryData(getGetCounterpartyByClientQueryKey(String(clientId)), next);
    }
  };
  // Х-8: отметка видна в списке («Не работаем») — списки клиентов и партнёров перечитываются
  const refreshLists = () => {
    void queryClient.invalidateQueries({ queryKey: getListCrmClientsQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getListCatalogSuppliersQueryKey() });
  };
  const setRole = useSetCounterpartyRole({ mutation: { onSuccess: store } });
  const { message } = App.useApp();
  // Х-8: «Снова работать» — обратимое действие, без вопроса; «Не работать» просит причину
  const clearMark = useClearCounterpartyDoNotWork({
    mutation: {
      onSuccess: (next) => {
        store(next);
        refreshLists();
        void message.success(t("counterparty.doNotWork.cleared"));
      },
    },
  });
  const conflict = setRole.error instanceof ApiError && setRole.error.status === 409;

  const items = [
    { key: "overview", label: t("counterparty.tabs.overview"), children: <Overview card={card} /> },
    ...(hasClient
      ? [
          {
            key: "client",
            label: t("counterparty.tabs.client"),
            children: <ClientPanel id={clientId} onClose={onClose} embedded />,
          },
        ]
      : []),
    ...(hasSupplier
      ? [
          {
            key: "supplier",
            label: t("counterparty.tabs.supplier"),
            children: <PartnerCard id={card.id} embedded />,
          },
        ]
      : []),
  ];

  return (
    <div className="pf-cp">
      <div className="pf-cp-head">
        <div className="pf-cp-title">
          <h3 className="pf-fp-title">{card.name}</h3>
          {requisitesEditable ? (
            <Button
              size="small"
              onClick={() => {
                setEditing(true);
              }}
            >
              {t("counterparty.requisites.edit")}
            </Button>
          ) : null}
          {requisitesEditable ? (
            card.do_not_work ? (
              <Button
                key="do-not-work-clear"
                size="small"
                loading={clearMark.isPending}
                onClick={() => {
                  clearMark.mutate({ id: card.id });
                }}
              >
                {t("counterparty.doNotWork.clear")}
              </Button>
            ) : (
              <Button
                key="do-not-work-set"
                size="small"
                type="text"
                onClick={() => {
                  setMarking(true);
                }}
              >
                {t("counterparty.doNotWork.set")}
              </Button>
            )
          ) : null}
        </div>
        <span className="pf-hint">
          {[card.inn ? `${t("card.inn")} ${card.inn}` : null, card.legal_address]
            .filter(Boolean)
            .join(" · ") || t("card.noInn")}
        </span>
      </div>
      <DoNotWorkStrip mark={card.do_not_work} />
      {clearMark.isError ? (
        <Alert type="warning" showIcon role="alert" message={t("counterparty.doNotWork.failed")} />
      ) : null}
      {marking ? (
        <DoNotWorkDialog
          card={card}
          onSaved={(next) => {
            store(next);
            refreshLists();
            setMarking(false);
          }}
          onCancel={() => {
            setMarking(false);
          }}
        />
      ) : null}
      {editing ? (
        <RequisitesSheet
          card={card}
          onSaved={(next) => {
            store(next);
            setEditing(false);
          }}
          onCancel={() => {
            setEditing(false);
          }}
        />
      ) : null}
      <ul className="pf-cp-roles" aria-label={t("counterparty.roles.label")}>
        {ROLE_ORDER.map((role) => {
          const on = card.roles[role];
          const togglable = editable && EDITABLE.some((code) => code === role);
          if (!on && !togglable) return null;
          const name = t(`counterparty.roles.${role}`);
          return (
            <li key={role}>
              {togglable ? (
                <Button
                  size="small"
                  shape="round"
                  type={on ? "primary" : "default"}
                  ghost={on}
                  aria-pressed={on}
                  loading={setRole.isPending && setRole.variables.data.role === role}
                  onClick={() => {
                    setRole.mutate({
                      id: card.id,
                      data: { role: role as CounterpartyRoleInRole, on: !on },
                    });
                  }}
                >
                  {on ? `✓ ${name}` : `+ ${name}`}
                </Button>
              ) : (
                <Tag>{name}</Tag>
              )}
            </li>
          );
        })}
      </ul>
      {setRole.isError ? (
        <Alert
          type="warning"
          showIcon
          role="alert"
          message={t(conflict ? "counterparty.roles.inUse" : "counterparty.roles.failed")}
        />
      ) : null}
      <Tabs
        className="pf-cp-tabs"
        size="small"
        activeKey={part}
        onChange={(key) => {
          setPart(key as Part);
        }}
        items={items}
      />
    </div>
  );
}

function Overview({ card }: { card: Card }) {
  const { t } = useTranslation("clients");
  return (
    <div className="pf-fp-stack">
      <section className="pf-fp-block" aria-labelledby={`pf-cp-${card.id}-people`}>
        <h4 id={`pf-cp-${card.id}-people`}>{t("counterparty.people.title")}</h4>
        {card.people.length ? (
          <ul className="pf-cp-list">
            {card.people.map((person) => (
              <li key={person.id}>
                <PersonCell
                  name={person.name}
                  caption={[
                    person.position,
                    person.is_primary ? t("counterparty.people.primary") : null,
                    person.has_cabinet ? t("counterparty.people.cabinet") : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                />
              </li>
            ))}
          </ul>
        ) : (
          <p className="pf-fp-sub">{t("counterparty.people.empty")}</p>
        )}
        {card.people.length ? (
          <Link className="pf-crm-link pf-focusable" to="/chats/contacts">
            {t("counterparty.people.contacts")}
          </Link>
        ) : null}
      </section>

      <section className="pf-fp-block" aria-labelledby={`pf-cp-${card.id}-bank`}>
        <h4 id={`pf-cp-${card.id}-bank`}>{t("counterparty.accounts.title")}</h4>
        {card.bank_accounts.length ? (
          <ul className="pf-cp-list">
            {card.bank_accounts.map((account) => (
              <li key={account.id}>
                <div>
                  {account.bank_name || t("counterparty.accounts.noBank")}{" "}
                  {account.is_default ? (
                    <Tag>
                      {t("counterparty.accounts.default", { currency: account.currency ?? "" })}
                    </Tag>
                  ) : (
                    <span className="pf-hint">{account.currency}</span>
                  )}
                </div>
                <div className="pf-num pf-hint">
                  {[
                    account.account,
                    account.mfo ? `${t("counterparty.accounts.mfo")} ${account.mfo}` : null,
                    account.swift ? `SWIFT ${account.swift}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="pf-fp-sub">{t("counterparty.accounts.empty")}</p>
        )}
        {card.accounts_masked && card.bank_accounts.length ? (
          <p className="pf-hint">{t("counterparty.accounts.masked")}</p>
        ) : null}
      </section>

      {card.roles.manufacturer || card.brands.length ? (
        <section className="pf-fp-block" aria-labelledby={`pf-cp-${card.id}-brands`}>
          <h4 id={`pf-cp-${card.id}-brands`}>{t("counterparty.brands.title")}</h4>
          {card.brands.length ? (
            <ul className="pf-cp-tags" aria-label={t("counterparty.brands.title")}>
              {card.brands.map((brand) => (
                <li key={brand.id}>
                  <Tag>{brand.name}</Tag>
                </li>
              ))}
            </ul>
          ) : (
            <p className="pf-fp-sub">{t("counterparty.brands.empty")}</p>
          )}
        </section>
      ) : null}
    </div>
  );
}

/** Реквизиты контрагента (СУЩ-2.7): их ведёт ERP, клиент CRM получает снимок; форма — в выезжающей панели. */
function RequisitesSheet({
  card,
  onSaved,
  onCancel,
}: {
  card: Card;
  onSaved: (next: Card) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("clients");
  const { message } = App.useApp();
  const [name, setName] = useState(card.name);
  const [inn, setInn] = useState(card.inn ?? "");
  const [registration, setRegistration] = useState(card.registration_number ?? "");
  const [address, setAddress] = useState(card.legal_address ?? "");
  const save = useUpdateCounterpartyRequisites({
    mutation: {
      onSuccess: (next) => {
        void message.success(t("counterparty.requisites.saved"));
        onSaved(next);
      },
    },
  });
  const innValid = inn.trim() === "" || /^\d{9}$/.test(inn.trim());
  const dirty =
    name !== card.name ||
    inn !== (card.inn ?? "") ||
    registration !== (card.registration_number ?? "") ||
    address !== (card.legal_address ?? "");
  const status = save.error instanceof ApiError ? save.error.status : null;
  const error = save.error
    ? t(
        status === 409
          ? "counterparty.requisites.exists"
          : status === 403
            ? "counterparty.requisites.forbidden"
            : "counterparty.requisites.failed",
      )
    : null;
  return (
    <FormSheet
      title={t("counterparty.requisites.title")}
      submitLabel={t("counterparty.requisites.submit")}
      saving={save.isPending}
      submitDisabled={!dirty || name.trim() === "" || !innValid}
      dirty={dirty}
      layer="drawer"
      error={<ErrorNote message={error} />}
      onSubmit={() => {
        save.mutate({
          id: card.id,
          data: {
            name: name.trim(),
            inn: inn.trim() || null,
            registration_number: registration.trim() || null,
            legal_address: address.trim() || null,
          },
        });
      }}
      onCancel={onCancel}
    >
      <FormField id="cp-req-name" label={t("counterparty.requisites.name")}>
        <Input
          id="cp-req-name"
          value={name}
          maxLength={255}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
      </FormField>
      <FormField
        id="cp-req-inn"
        label={t("counterparty.requisites.inn")}
        hint={t("counterparty.requisites.innHint")}
      >
        <Input
          id="cp-req-inn"
          value={inn}
          maxLength={9}
          inputMode="numeric"
          status={innValid ? undefined : "error"}
          aria-invalid={!innValid || undefined}
          aria-describedby="cp-req-inn-hint"
          onChange={(event) => {
            setInn(event.target.value);
          }}
        />
      </FormField>
      <FormField id="cp-req-registration" label={t("counterparty.requisites.registration")}>
        <Input
          id="cp-req-registration"
          value={registration}
          maxLength={64}
          onChange={(event) => {
            setRegistration(event.target.value);
          }}
        />
      </FormField>
      <FormField id="cp-req-address" label={t("counterparty.requisites.address")}>
        <Input.TextArea
          id="cp-req-address"
          value={address}
          maxLength={1000}
          autoSize={{ minRows: 2, maxRows: 5 }}
          onChange={(event) => {
            setAddress(event.target.value);
          }}
        />
      </FormField>
    </FormSheet>
  );
}

/** «Не работать» (Х-8): причина обязательна, дата окончания — по желанию; окно по центру — две строки формы. */
function DoNotWorkDialog({
  card,
  onSaved,
  onCancel,
}: {
  card: Card;
  onSaved: (next: Card) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("clients");
  const { message } = App.useApp();
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const save = useSetCounterpartyDoNotWork({
    mutation: {
      onSuccess: (next) => {
        void message.success(t("counterparty.doNotWork.marked"));
        onSaved(next);
      },
    },
  });
  const status = save.error instanceof ApiError ? save.error.status : null;
  const error = save.error
    ? t(
        status === 403
          ? "counterparty.doNotWork.forbidden"
          : status === 422
            ? "counterparty.doNotWork.untilPast"
            : "counterparty.doNotWork.failed",
      )
    : null;
  return (
    <Dialog
      title={t("counterparty.doNotWork.title")}
      okLabel={t("counterparty.doNotWork.submit")}
      okDisabled={reason.trim() === ""}
      loading={save.isPending}
      danger
      onOk={() => {
        save.mutate({
          id: card.id,
          data: { reason: reason.trim(), until: until || null },
        });
      }}
      onCancel={onCancel}
    >
      <div className="pf-fp-stack">
        <FormField
          id="cp-dnw-reason"
          label={t("counterparty.doNotWork.reason")}
          hint={t("counterparty.doNotWork.reasonHint")}
        >
          <Input.TextArea
            id="cp-dnw-reason"
            value={reason}
            maxLength={1000}
            autoSize={{ minRows: 3, maxRows: 6 }}
            aria-describedby="cp-dnw-reason-hint"
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
        </FormField>
        <FormField id="cp-dnw-until" label={t("counterparty.doNotWork.until")}>
          <DateField
            id="cp-dnw-until"
            value={until}
            min={companyToday()}
            onChange={setUntil}
            allowClear
          />
        </FormField>
        <ErrorNote message={error} />
      </div>
    </Dialog>
  );
}
