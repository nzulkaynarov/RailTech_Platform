import { Descriptions, List, Space, Typography } from "antd";
import { useParams } from "react-router";

import {
  useClient,
  useClientContacts,
  useClientDocuments,
  useClientReceivables,
} from "../../api/adminQueries";
import { useDeals } from "../../api/dealQueries";
import type { ClientDetail } from "../../api/generated/model";
import { usePermissionsQuery } from "../../api/queries";
import { useEntityDocumentTitle } from "../../app/documentTitle";
import { allowed } from "../../app/providers/access";
import { BooleanTag } from "../../components/BooleanTag";
import { LeadLink } from "../../components/EntityLink";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { StageBadge } from "../../components/StageBadge";
import { type UrlTab, UrlTabs } from "../../components/UrlTabs";
import { segmentLabel } from "../../domain/labels";
import { t } from "../../i18n/ru";
import { formatMoney } from "../../domain/deals";
import { formatDate } from "../../lib/time";
import { ClientDeals } from "../deals/ClientDeals";
import { ClientContacts } from "./ClientContacts";
import { ClientDocuments } from "./ClientDocuments";
import { ClientTelegram } from "./ClientTelegram";
import { EditClient } from "./EditClient";
import { HandoffState } from "./HandoffState";
import { ServiceRequests } from "./ServiceRequests";
import "../admin.css";

/** Долг клиента по валютам: каждая валюта отдельно; «Долга нет», если ERP вернула пустой список. */
function Receivables({ items }: { items: { amount: string; currency: string }[] }) {
  if (items.length === 0) return <Typography.Text>{t.clients.receivablesNone}</Typography.Text>;
  return (
    <Space size={[16, 0]} wrap title={t.clients.receivablesHint}>
      {items.map((money) => (
        <Typography.Text key={money.currency} strong>
          {formatMoney(money.amount, money.currency)}
        </Typography.Text>
      ))}
    </Space>
  );
}

/** Реквизиты — одной строкой под названием клиента. */
function Details({ data }: { data: ClientDetail }) {
  const debt = useClientReceivables(data.id, Boolean(data.erp_company_id)).data;
  return (
    <Descriptions
      size="small"
      column={{ xs: 1, sm: 3 }}
      aria-label={t.clients.details}
      items={[
        { key: "inn", label: t.clients.inn, children: data.inn ?? t.common.none },
        { key: "segment", label: t.clients.segment, children: segmentLabel(data.segment) },
        {
          key: "status",
          label: t.clients.status,
          children: (
            <BooleanTag value={data.is_active} yes={t.clients.active} no={t.clients.inactive} />
          ),
        },
        ...(data.erp_company_id
          ? [
              {
                key: "erp",
                label: t.clients.inBackoffice,
                children: `${t.clients.backofficeCompany} #${String(data.erp_company_id)}`,
              },
            ]
          : []),
        // Нет данных (ERP не отвечает, старше шва 0.3.0, лимит частоты) — блока нет, как раньше.
        ...(debt?.status === "ok"
          ? [
              {
                key: "receivables",
                label: t.clients.receivables,
                children: <Receivables items={debt.receivables} />,
              },
            ]
          : []),
      ]}
    />
  );
}

/** Лиды клиента: имя · стадия · дата, чтобы строка была понятна без открытия. */
function Leads({ data }: { data: ClientDetail }) {
  return (
    <List
      size="small"
      dataSource={data.leads}
      locale={{
        emptyText: <Typography.Text type="secondary">{t.clients.leadsEmpty}</Typography.Text>,
      }}
      renderItem={(lead) => (
        <List.Item>
          <Space wrap>
            <LeadLink id={lead.id} name={lead.display_name} />
            <StageBadge stage={lead.stage} />
            <Typography.Text type="secondary">{formatDate(lead.created_at)}</Typography.Text>
          </Space>
        </List.Item>
      )}
    />
  );
}

/** Название вкладки со счётчиком; пока данные грузятся — без числа. */
function TabLabel({ tab, count }: { tab: string; count: number | undefined }) {
  return (
    <Space size={6}>
      {t.clients.tabs[tab]}
      {count === undefined ? null : <Typography.Text type="secondary">{count}</Typography.Text>}
    </Space>
  );
}

// Счётчики берут те же запросы, что и вкладки (кэш react-query), — лишних запросов нет.
function ContactsLabel({ id }: { id: number }) {
  return <TabLabel tab="contacts" count={useClientContacts(id).data?.contacts.length} />;
}
function DealsLabel({ id }: { id: number }) {
  return <TabLabel tab="deals" count={useDeals({ client_id: id }).data?.length} />;
}
function DocumentsLabel({ id }: { id: number }) {
  return <TabLabel tab="documents" count={useClientDocuments(id).data?.length} />;
}

/** Вкладки по правам: сделки и документы — только тем, кому они доступны. */
function useClientTabs(id: number, data: ClientDetail): UrlTab[] {
  const perms = usePermissionsQuery();
  const canWrite = allowed(perms.data, "clients", "write");
  const tabs: (UrlTab | null)[] = [
    {
      key: "contacts",
      label: <ContactsLabel id={id} />,
      children: <ClientContacts clientId={id} canWrite={canWrite} />,
    },
    allowed(perms.data, "deals", "read")
      ? {
          key: "deals",
          label: <DealsLabel id={id} />,
          children: <ClientDeals clientId={id} canWrite={allowed(perms.data, "deals", "write")} />,
        }
      : null,
    {
      key: "leads",
      label: <TabLabel tab="leads" count={data.leads.length} />,
      children: <Leads data={data} />,
    },
    {
      key: "requests",
      label: <TabLabel tab="requests" count={data.service_requests.length} />,
      children: (
        <ServiceRequests clientId={id} requests={data.service_requests} canWrite={canWrite} />
      ),
    },
    allowed(perms.data, "documents", "read")
      ? {
          key: "documents",
          label: <DocumentsLabel id={id} />,
          children: (
            <ClientDocuments clientId={id} canWrite={allowed(perms.data, "documents", "write")} />
          ),
        }
      : null,
    {
      key: "telegram",
      label: <TabLabel tab="telegram" count={data.identities.length} />,
      children: <ClientTelegram data={data} canWrite={canWrite} />,
    },
  ];
  return tabs.filter((tab): tab is UrlTab => tab !== null);
}

function ClientTabs({ id, data }: { id: number; data: ClientDetail }) {
  return <UrlTabs label={t.clients.sections} items={useClientTabs(id, data)} />;
}

/**
 * Карточка клиента (SPEC §10.1, §7.3; UX волна 3): реквизиты одной строкой в шапке, ниже вкладки
 * «Контакты · Сделки · Лиды · Запросы · Документы · Telegram» со счётчиками; вкладка — в `?tab=`.
 */
export function ClientDetailPage() {
  const id = Number(useParams()["id"]);
  const query = useClient(id);
  const data = query.data;
  const perms = usePermissionsQuery();
  const canWrite = allowed(perms.data, "clients", "write");
  useEntityDocumentTitle(data?.name);
  if (!data) {
    return (
      <PageState query={query} ready={false}>
        {null}
      </PageState>
    );
  }
  return (
    <PageBody>
      <PageHeader
        back="/clients"
        title={data.name}
        extra={canWrite ? <EditClient client={data} /> : null}
      />
      <Details data={data} />
      <HandoffState client={data} canWrite={canWrite} />
      <ClientTabs id={id} data={data} />
    </PageBody>
  );
}
