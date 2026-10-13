import { Alert, Card, Descriptions, Grid, Space, Splitter, Tabs, Tag, Typography } from "antd";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router";

import type { LeadDetail } from "../../api/generated/model";
import {
  useDecisions,
  useLead,
  useLeadAction,
  useMe,
  useMessages,
  usePermissionsQuery,
  useTeam,
} from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { ChatThread } from "../../components/ChatThread";
import { DecisionsPanel } from "../../components/DecisionsPanel";
import { LeadActions, OwnerBanner } from "../../components/LeadActions";
import { type ActionRights, leadActionPlan, replyState } from "../../components/leadActionRules";
import { Owner } from "../../components/Owner";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { QueueNav } from "../../components/QueueNav";
import { LangTag, PriorityTag, StageBadge } from "../../components/StageBadge";
import { leadLinkText } from "../../domain/entities";
import { reasonLabel } from "../../domain/labels";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useReplyAssist } from "../../hooks/useReplyAssist";
import { t } from "../../i18n/ru";
import { readSplit, saveSplit } from "../../lib/splitSize";
import "../../styles/workspace.css";
import { LeadDeals } from "./LeadDeals";
import { LeadNotes, LeadSummary } from "./LeadSummary";
import "../pages.css";

const useRightsMatrix = () => usePermissionsQuery().data;

function useRights(): ActionRights | null {
  const me = useMe();
  const perms = usePermissionsQuery();
  if (!me.data) return null;
  return {
    take: allowed(perms.data, "leads", "take"),
    work: allowed(perms.data, "leads", "work"),
    note: allowed(perms.data, "leads", "note"),
    reply: allowed(perms.data, "leads", "reply"),
    assist: allowed(perms.data, "leads", "assist"),
    clients: allowed(perms.data, "clients", "write"),
    userId: me.data.id,
    isAdmin: me.data.roles.includes("admin"),
  };
}

function Chat({ lead, rights }: { lead: LeadDetail; rights: ActionRights }) {
  const messages = useMessages(lead.id);
  const team = useTeam();
  const action = useLeadAction(lead.id);
  const onError = useApiErrorToast();
  const reply = replyState(lead, rights);
  const assist = useReplyAssist(lead.id);
  const me = useMe();
  const canTemplates = allowed(useRightsMatrix(), "reply_templates", "read");
  const templates = canTemplates
    ? {
        language: lead.language,
        name: lead.display_name,
        manager: me.data?.full_name ?? lead.assigned_user_name ?? "",
      }
    : undefined;
  const authorName = (userId: number) => team.data?.find((m) => m.id === userId)?.full_name;
  const send = async (text: string) => {
    try {
      await action.mutateAsync({ kind: "reply", text });
    } catch (error) {
      onError(error);
      throw error;
    }
  };
  return (
    <PageState query={messages} variant="section">
      <ChatThread
        messages={messages.data ?? []}
        canReply={reply.can}
        hint={reply.hint}
        sending={action.isPending}
        language={lead.language}
        authorName={authorName}
        onSend={send}
        assist={rights.assist ? assist : undefined}
        templates={templates}
      />
    </PageState>
  );
}

type Panes = {
  chat: ReactNode;
  summary: ReactNode;
  why: ReactNode;
  notes: ReactNode;
  deals: ReactNode;
};

/** Телефон: вкладки, переписка первой (U-12); сделки — во вкладке «Детали». */
function PhoneTabs({ chat, summary, why, notes, deals }: Panes) {
  const details = (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      {summary}
      {deals ? (
        <div>
          <Typography.Text strong>{t.lead.tabs.deals}</Typography.Text>
          {deals}
        </div>
      ) : null}
    </Space>
  );
  return (
    <Tabs
      items={[
        { key: "chat", label: t.lead.tabs.chat, children: chat },
        { key: "details", label: t.lead.tabs.details, children: details },
        { key: "why", label: t.lead.tabs.why, children: why },
        { key: "notes", label: t.lead.tabs.notes, children: notes },
      ]}
    />
  );
}

/** Доля переписки по умолчанию и пределы перетаскивания (вкладки справа не уже ≈ 300 px). */
const CHAT_SPLIT = { fallback: 65, min: 40, max: 75 };
const SPLIT_KEY = "lead";

/**
 * Переписка | вкладки в antd `Splitter`: ширину меняют перетаскиванием разделителя,
 * доля запоминается в браузере (Refine/antd P2, п. 7).
 */
function SplitPanes({ start, end }: { start: ReactNode; end: ReactNode }) {
  return (
    <Splitter
      onResizeEnd={(sizes) => {
        saveSplit(SPLIT_KEY, sizes);
      }}
    >
      <Splitter.Panel
        className="split-start"
        defaultSize={readSplit(SPLIT_KEY, CHAT_SPLIT)}
        min={`${String(CHAT_SPLIT.min)}%`}
        max={`${String(CHAT_SPLIT.max)}%`}
      >
        {start}
      </Splitter.Panel>
      <Splitter.Panel className="split-end">{end}</Splitter.Panel>
    </Splitter>
  );
}

/**
 * Десктоп (≥ lg): переписка — основная ширина, справа вкладки «Резюме · Почему · Заметки · Сделки»
 * (UX волна 2), между ними перетаскиваемый разделитель. Планшет — те же карточки друг под другом.
 */
function Layout(panes: Panes) {
  const screens = Grid.useBreakpoint();
  if (screens.md === false) return <PhoneTabs {...panes} />;
  const { chat, summary, why, notes, deals } = panes;
  const side = [
    { key: "summary", label: t.lead.tabs.summary, children: summary },
    { key: "why", label: t.lead.tabs.why, children: why },
    { key: "notes", label: t.lead.tabs.notes, children: notes },
    ...(deals ? [{ key: "deals", label: t.lead.tabs.deals, children: deals }] : []),
  ];
  const chatCard = (
    <Card size="small" title={t.lead.chat}>
      {chat}
    </Card>
  );
  const sideCard = (
    <Card size="small" className="lead-side">
      <Tabs size="small" items={side} />
    </Card>
  );
  if (screens.lg === true) return <SplitPanes start={chatCard} end={sideCard} />;
  return (
    <div className="lead-grid">
      {chatCard}
      {sideCard}
    </div>
  );
}

/**
 * Сводка в шапке: стадия, кто ведёт, телефон, язык, оценка. На широком экране — одной строкой,
 * подпись над значением (`layout="vertical"`): в пять колонок «подпись: значение» длинный статус
 * «Ждёт менеджера · N мин» и телефон налезали на соседние поля.
 */
function LeadFacts({ lead }: { lead: LeadDetail }) {
  const wide = Grid.useBreakpoint().lg === true;
  return (
    <Descriptions
      size="small"
      className="lead-facts"
      layout={wide ? "vertical" : "horizontal"}
      column={{ xs: 1, sm: 2, md: 3, lg: 5, xl: 5, xxl: 5 }}
      items={[
        { key: "stage", label: t.leads.stage, children: <StageBadge stage={lead.stage} /> },
        { key: "owner", label: t.leads.whoLeads, children: <Owner lead={lead} /> },
        {
          key: "phone",
          label: t.lead.phone,
          children: lead.phone_e164 ? (
            <Typography.Text
              className="nowrap"
              copyable={{ text: lead.phone_e164, tooltips: [t.lead.copy, t.lead.copied] }}
            >
              <a href={`tel:${lead.phone_e164}`}>{lead.phone_e164}</a>
            </Typography.Text>
          ) : (
            t.common.none
          ),
        },
        { key: "lang", label: t.leads.language, children: <LangTag language={lead.language} /> },
        { key: "score", label: t.leads.score, children: lead.score },
      ]}
    />
  );
}

/** Причины передачи тегами в шапке; текст причины и рекомендация — во вкладке «Резюме». */
function HandoffTags({ lead }: { lead: LeadDetail }) {
  const e = lead.escalation;
  if (!e) return null;
  return (
    <Space wrap size={4} aria-label={t.lead.escalation} role="group">
      <PriorityTag priority={e.priority} />
      {e.reason_codes.map((code) => (
        <Tag key={code}>{reasonLabel(code)}</Tag>
      ))}
    </Space>
  );
}

/** Шапка: имя, сводка `Descriptions`, причины передачи, действия и баннер «Лида ведёт …». */
function LeadHeader({ lead, rights }: { lead: LeadDetail; rights: ActionRights }) {
  const plan = leadActionPlan(lead, rights);
  return (
    <PageHeader
      back="/leads"
      nav={rights.take ? <QueueNav leadId={lead.id} /> : null}
      title={leadLinkText(lead.id, lead.display_name)}
      extra={<LeadActions lead={lead} rights={rights} />}
    >
      <div className="lead-meta">
        <LeadFacts lead={lead} />
        <HandoffTags lead={lead} />
      </div>
      {plan.ownerBanner ? (
        <div className="lead-banner">
          <OwnerBanner banner={plan.ownerBanner} />
        </div>
      ) : null}
      {lead.open_service_request_id && lead.client_id ? (
        <div className="lead-banner">
          <Alert
            type="info"
            showIcon
            message={t.lead.openRequest}
            description={t.lead.openRequestHint}
            action={<Link to={`/clients/${String(lead.client_id)}`}>{t.inbox.openClient}</Link>}
          />
        </div>
      ) : null}
    </PageHeader>
  );
}

/** Карточка лида (SPEC §10.1): шапка-сводка · переписка · вкладки «Резюме · Почему · Заметки · Сделки». */
export function LeadDetailPage() {
  const id = Number(useParams()["id"]);
  const lead = useLead(id);
  const decisions = useDecisions(id);
  const rights = useRights();
  const canDeals = allowed(useRightsMatrix(), "deals", "read");
  return (
    <PageState query={lead} ready={Boolean(lead.data && rights)}>
      {lead.data && rights ? (
        <PageBody>
          <LeadHeader lead={lead.data} rights={rights} />
          <Layout
            chat={<Chat lead={lead.data} rights={rights} />}
            summary={<LeadSummary lead={lead.data} />}
            why={<DecisionsPanel query={decisions} isAdmin={rights.isAdmin} />}
            notes={<LeadNotes leadId={id} canNote={rights.note} />}
            deals={canDeals ? <LeadDeals lead={lead.data} /> : null}
          />
        </PageBody>
      ) : null}
    </PageState>
  );
}
