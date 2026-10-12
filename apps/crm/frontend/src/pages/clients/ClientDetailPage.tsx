import { Card, Descriptions, List, Space, Typography } from "antd";
import { useParams } from "react-router";

import { useClient } from "../../api/adminQueries";
import type { ClientDetail } from "../../api/generated/model";
import { usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { BooleanTag } from "../../components/BooleanTag";
import { LeadLink } from "../../components/EntityLink";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { StageBadge } from "../../components/StageBadge";
import { t } from "../../i18n/ru";
import { formatDate } from "../../lib/time";
import { ClientDeals } from "../deals/ClientDeals";
import { ClientDocuments } from "./ClientDocuments";
import { ClientTelegram } from "./ClientTelegram";
import { EditClient } from "./EditClient";
import { ServiceRequests } from "./ServiceRequests";
import "../admin.css";

function Details({ data }: { data: ClientDetail }) {
  return (
    <Card size="small" title={t.clients.details}>
      <Descriptions size="small" column={{ xs: 1, md: 3 }}>
        <Descriptions.Item label={t.clients.inn}>{data.inn ?? t.common.none}</Descriptions.Item>
        <Descriptions.Item label={t.clients.segment}>
          {data.segment ?? t.common.none}
        </Descriptions.Item>
        <Descriptions.Item label={t.clients.status}>
          <BooleanTag value={data.is_active} yes={t.clients.active} no={t.clients.inactive} />
        </Descriptions.Item>
      </Descriptions>
    </Card>
  );
}

/** Лиды клиента: имя · стадия · дата, чтобы строка была понятна без открытия. */
function Leads({ data }: { data: ClientDetail }) {
  return (
    <Card size="small" title={t.clients.leads}>
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
    </Card>
  );
}

/** Карточка клиента (SPEC §10.1, §7.3): Telegram с подтверждением, лиды, документы, запросы. */
export function ClientDetailPage() {
  const id = Number(useParams()["id"]);
  const query = useClient(id);
  const data = query.data;
  const perms = usePermissionsQuery();
  const canWrite = allowed(perms.data, "clients", "write");
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
      <ClientTelegram data={data} canWrite={canWrite} />
      <Leads data={data} />
      {allowed(perms.data, "deals", "read") ? (
        <ClientDeals clientId={id} canWrite={allowed(perms.data, "deals", "write")} />
      ) : null}
      {allowed(perms.data, "documents", "read") ? (
        <Card size="small" title={t.clients.documents}>
          <ClientDocuments clientId={id} canWrite={allowed(perms.data, "documents", "write")} />
        </Card>
      ) : null}
      <Card size="small" title={t.clients.requests}>
        <ServiceRequests clientId={id} requests={data.service_requests} canWrite={canWrite} />
      </Card>
    </PageBody>
  );
}
