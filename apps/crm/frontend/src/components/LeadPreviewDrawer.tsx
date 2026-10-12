import { Button, Descriptions, Drawer, Grid, List, Space, Typography } from "antd";
import { useNavigate } from "react-router";

import type { LeadDetail, MessageOut } from "../api/generated/model";
import { useLead, useMessages } from "../api/queries";
import { leadLinkText } from "../domain/entities";
import { useTakeAndOpen } from "../hooks/useLeadActionRunner";
import { t } from "../i18n/ru";
import { formatWhen } from "../lib/time";
import { EmptyState } from "./EmptyState";
import { EscalationReason } from "./EscalationReason";
import { Owner } from "./Owner";
import { PageState } from "./PageState";
import { LangTag, StageBadge } from "./StageBadge";

const LAST_MESSAGES = 5;

/** «Забрать» прямо из списка и сразу в карточку лида (как Intercom «Assign to me»). */
export function TakeButton({ leadId, size }: { leadId: number; size?: "small" | "middle" }) {
  const { takeAndOpen, busy } = useTakeAndOpen(leadId);
  const phone = Grid.useBreakpoint().sm === false;
  return (
    <Button
      size={phone ? "large" : (size ?? "small")}
      block={phone}
      type="primary"
      className="touch-target"
      loading={busy}
      onClick={() => void takeAndOpen()}
    >
      {t.actions.take}
    </Button>
  );
}

function LastMessages({ leadId }: { leadId: number }) {
  const messages = useMessages(leadId);
  const items: MessageOut[] = (messages.data ?? []).slice(-LAST_MESSAGES);
  return (
    <PageState query={messages} variant="section">
      {items.length ? (
        <List
          size="small"
          dataSource={items}
          renderItem={(m) => (
            <List.Item key={m.id}>
              <Space direction="vertical" size={0}>
                <Typography.Text type="secondary">
                  {t.roleNames[m.role] ?? m.role} · {formatWhen(m.created_at)}
                </Typography.Text>
                <Typography.Paragraph ellipsis={{ rows: 3 }}>{m.text}</Typography.Paragraph>
              </Space>
            </List.Item>
          )}
        />
      ) : (
        <EmptyState compact title={t.leadPreview.noMessages} />
      )}
    </PageState>
  );
}

function Summary({ lead }: { lead: LeadDetail }) {
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label={t.leads.stage}>
          <StageBadge stage={lead.stage} />
        </Descriptions.Item>
        <Descriptions.Item label={t.leads.whoLeads}>
          <Owner lead={lead} />
        </Descriptions.Item>
        <Descriptions.Item label={t.lead.phone}>
          {lead.phone_e164 ? (
            <a className="nowrap" href={`tel:${lead.phone_e164}`}>
              {lead.phone_e164}
            </a>
          ) : (
            t.common.none
          )}
        </Descriptions.Item>
        <Descriptions.Item label={t.leads.language}>
          <LangTag language={lead.language} />
        </Descriptions.Item>
        <Descriptions.Item label={t.leads.score}>{lead.score}</Descriptions.Item>
        <Descriptions.Item label={t.leads.need}>
          {lead.need_summary ?? t.common.none}
        </Descriptions.Item>
      </Descriptions>
      {lead.escalation ? (
        <div>
          <Typography.Text strong>{t.lead.escalation}</Typography.Text>
          <EscalationReason escalation={lead.escalation} />
        </div>
      ) : null}
      <div>
        <Typography.Text strong>{t.leadPreview.lastMessages}</Typography.Text>
        <LastMessages leadId={lead.id} />
      </div>
    </Space>
  );
}

type Props = {
  /** Открытый лид; `null` — панель закрыта. */
  leadId: number | null;
  onClose: () => void;
  /** Показать «Забрать» (есть право и лид ещё не у менеджера). */
  canTake: boolean;
};

function Body({ leadId, canTake, onClose }: Props & { leadId: number }) {
  const lead = useLead(leadId);
  const navigate = useNavigate();
  const data = lead.data;
  const free = data ? data.owner_mode !== "human" : false;
  return (
    <Drawer
      open
      width={420}
      onClose={onClose}
      title={data ? leadLinkText(data.id, data.display_name) : leadLinkText(leadId)}
      footer={
        <Space wrap>
          <Button
            type={canTake && free ? "default" : "primary"}
            onClick={() => void navigate(`/leads/${String(leadId)}`)}
          >
            {t.leadPreview.openCard}
          </Button>
          {canTake && free ? <TakeButton leadId={leadId} size="middle" /> : null}
        </Space>
      }
    >
      <PageState query={lead} variant="section">
        {data ? <Summary lead={data} /> : null}
      </PageState>
    </Drawer>
  );
}

/**
 * Краткая сводка лида справа (UX волна 2, принцип «детали — в боковой панели»): список остаётся
 * на месте, полная карточка — по кнопке «Открыть карточку». Один компонент для «Входящих» и «Лидов».
 */
export function LeadPreviewDrawer(props: Props) {
  if (props.leadId === null) return null;
  return <Body {...props} leadId={props.leadId} />;
}
