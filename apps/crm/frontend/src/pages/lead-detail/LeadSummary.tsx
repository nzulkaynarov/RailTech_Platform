import { Card, Descriptions, List, Space, Tag, Typography } from "antd";
import { Link } from "react-router";

import type { LeadDetail } from "../../api/generated/model";
import { useNotes } from "../../api/queries";
import { EscalationReason } from "../../components/EscalationReason";
import { SectionError } from "../../components/PageState";
import { LangTag } from "../../components/StageBadge";
import { productLabel, QUALIFICATION_KEYS, qualificationText } from "../../domain/labels";
import { useProductNames } from "../../hooks/useProductNames";
import { t } from "../../i18n/ru";
import { formatDate, formatWhen } from "../../lib/time";

function Qualification({ lead }: { lead: LeadDetail }) {
  const productName = useProductNames();
  const q = lead.qualification as Record<string, unknown>;
  const keys = QUALIFICATION_KEYS.filter((k) => q[k]);
  if (!keys.length && !lead.product_interest.length) return null;
  return (
    <>
      <Typography.Text strong>{t.lead.qualification}</Typography.Text>
      <div>
        {keys.map((k) => (
          <Tag key={k}>{qualificationText(k, q[k])}</Tag>
        ))}
        {lead.product_interest.map((p) => (
          <Tag color={productLabel(p).color} key={p}>
            {productName(p)}
          </Tag>
        ))}
      </div>
    </>
  );
}

export function LeadSummary({ lead }: { lead: LeadDetail }) {
  return (
    <Card size="small" title={t.lead.summary}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label={t.leads.score}>{lead.score}</Descriptions.Item>
        {lead.client_id ? (
          <Descriptions.Item label={t.lead.client}>
            <Link to={`/clients/${String(lead.client_id)}`}>{t.lead.openClient}</Link>
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label={t.leads.language}>
          <LangTag language={lead.language} />
        </Descriptions.Item>
        <Descriptions.Item label={t.lead.consent}>
          {lead.consent_given_at ? formatDate(lead.consent_given_at) : t.lead.consentNo}
        </Descriptions.Item>
        <Descriptions.Item label={t.leads.need}>
          {lead.need_summary ?? t.common.none}
        </Descriptions.Item>
        <Descriptions.Item label={t.clients.accessTg}>
          {lead.tg_username ? `@${lead.tg_username}` : t.common.none}
        </Descriptions.Item>
        <Descriptions.Item label={t.lead.phone}>
          {lead.phone_e164 ? (
            <a href={`tel:${lead.phone_e164}`}>{lead.phone_e164}</a>
          ) : (
            t.common.none
          )}
        </Descriptions.Item>
      </Descriptions>
      <Qualification lead={lead} />
      {lead.escalation ? (
        <>
          <Typography.Text strong>{t.lead.escalation}</Typography.Text>
          <div>
            <EscalationReason escalation={lead.escalation} />
          </div>
        </>
      ) : null}
    </Card>
  );
}

export function LeadNotes({ leadId }: { leadId: number }) {
  const notes = useNotes(leadId);
  const data = notes.data;
  if (notes.isError) {
    return (
      <SectionError
        error={notes.error}
        onRetry={() => {
          void notes.refetch();
        }}
      />
    );
  }
  if (!data?.length) return null;
  return (
    <Card size="small" title={t.lead.notes}>
      <List
        size="small"
        dataSource={data}
        renderItem={(n) => (
          <List.Item>
            <Space direction="vertical" size={0}>
              <Typography.Text>{n.text}</Typography.Text>
              <Typography.Text type="secondary">
                {formatWhen(n.created_at)} {n.visible_to_bot ? `· ${t.actions.noteForBot}` : ""}
              </Typography.Text>
            </Space>
          </List.Item>
        )}
      />
    </Card>
  );
}
