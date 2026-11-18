import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Skeleton, Tabs, Tag } from "antd";
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
  useGetCounterparty,
  useGetCounterpartyByClient,
  useSetCounterpartyRole,
} from "../../../shared/api/generated/platform-bff";
import { PersonCell } from "../../../shared/ui/EntityCell";
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
  const hasClient = seesClients && clientId !== null;
  const hasSupplier = seesStock && (card.roles.supplier || card.roles.manufacturer);
  const first: Part =
    entry === "client" && hasClient
      ? "client"
      : entry === "supplier" && hasSupplier
        ? "supplier"
        : "overview";
  const [part, setPart] = useState<Part>(first);

  const setRole = useSetCounterpartyRole({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetCounterpartyQueryKey(card.id), next);
        if (clientId !== null) {
          queryClient.setQueryData(getGetCounterpartyByClientQueryKey(String(clientId)), next);
        }
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
        <h3 className="pf-fp-title">{card.name}</h3>
        <span className="pf-hint">
          {[card.inn ? `${t("card.inn")} ${card.inn}` : null, card.legal_address]
            .filter(Boolean)
            .join(" · ") || t("card.noInn")}
        </span>
      </div>
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
