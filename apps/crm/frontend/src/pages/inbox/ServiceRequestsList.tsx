import type { UseQueryResult } from "@tanstack/react-query";
import { Button, List, Tag, Typography } from "antd";
import { Link } from "react-router";

import type { ServiceRequestItem } from "../../api/generated/model";
import { LeadLink } from "../../components/EntityLink";
import { PageState } from "../../components/PageState";
import { formatWait } from "../../domain/sla";
import { t } from "../../i18n/ru";
import { formatDateTime } from "../../lib/time";

function RequestItem({ request, now }: { request: ServiceRequestItem; now: Date }) {
  const since = new Date(request.created_at);
  const wait = formatWait(Math.max(0, now.getTime() - since.getTime()));
  return (
    <List.Item
      actions={[
        <Button key="client" size="small" className="touch-target">
          <Link to={`/clients/${String(request.client_id)}`}>{t.inbox.openClient}</Link>
        </Button>,
      ]}
    >
      <List.Item.Meta
        title={
          <span className="inbox-item-title">
            <Link to={`/clients/${String(request.client_id)}`}>{request.client_name}</Link>
            <Tag>
              <time dateTime={request.created_at} title={formatDateTime(request.created_at)}>
                {t.inbox.requestWaiting.replace("{time}", wait)}
              </time>
            </Tag>
          </span>
        }
        description={
          <span className="lead-card-row">
            <Typography.Text>{request.summary}</Typography.Text>
            {request.lead_id ? <LeadLink id={request.lead_id} /> : null}
          </span>
        }
      />
    </List.Item>
  );
}

type Props = { query: UseQueryResult<ServiceRequestItem[]>; now: Date };

/** Вкладка «Запросы клиентов» (Q-017): самый долгий — первым, закрытие — в карточке клиента. */
export function ServiceRequestsList({ query, now }: Props) {
  const items = query.data ?? [];
  return (
    <PageState
      query={query}
      variant="section"
      empty={
        query.data && !items.length
          ? { compact: true, title: t.inbox.emptyRequests, hint: t.inbox.emptyRequestsHint }
          : null
      }
    >
      <List
        size="small"
        dataSource={items}
        renderItem={(request) => <RequestItem request={request} now={now} />}
      />
    </PageState>
  );
}
