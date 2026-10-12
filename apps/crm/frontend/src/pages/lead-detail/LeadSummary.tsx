import { PlusOutlined } from "@ant-design/icons";
import { Button, Descriptions, List, Space, Tag, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router";

import type { LeadDetail } from "../../api/generated/model";
import { useNotes } from "../../api/queries";
import { EmptyState } from "../../components/EmptyState";
import { EscalationReason } from "../../components/EscalationReason";
import { LeadActionDialog } from "../../components/LeadActionDialog";
import { SectionError } from "../../components/PageState";
import { productLabel, QUALIFICATION_KEYS, qualificationText } from "../../domain/labels";
import { useLeadActionRunner } from "../../hooks/useLeadActionRunner";
import { useProductNames } from "../../hooks/useProductNames";
import { t } from "../../i18n/ru";
import { formatDate, formatWhen } from "../../lib/time";

function Qualification({ lead }: { lead: LeadDetail }) {
  const productName = useProductNames();
  const q = lead.qualification as Record<string, unknown>;
  const keys = QUALIFICATION_KEYS.filter((k) => q[k]);
  if (!keys.length && !lead.product_interest.length) return null;
  return (
    <div>
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
    </div>
  );
}

/**
 * Вкладка «Резюме»: потребность, клиент, согласие, Telegram, телефон клиента, квалификация,
 * причина передачи с рекомендацией. Стадия, ответственный, телефон, язык и оценка — в шапке.
 */
export function LeadSummary({ lead }: { lead: LeadDetail }) {
  return (
    <Space direction="vertical" size="small" style={{ width: "100%" }}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label={t.leads.need}>
          {lead.need_summary ?? t.common.none}
        </Descriptions.Item>
        {lead.client_id ? (
          <Descriptions.Item label={t.lead.client}>
            <Link to={`/clients/${String(lead.client_id)}`}>{t.lead.openClient}</Link>
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label={t.lead.consent}>
          {lead.consent_given_at ? formatDate(lead.consent_given_at) : t.lead.consentNo}
        </Descriptions.Item>
        <Descriptions.Item label={t.clients.accessTg}>
          {lead.tg_username ? `@${lead.tg_username}` : t.common.none}
        </Descriptions.Item>
        {lead.client_phone_e164 ? (
          <Descriptions.Item label={t.lead.clientPhone}>
            <a className="nowrap" href={`tel:${lead.client_phone_e164}`}>
              {lead.client_phone_e164}
            </a>
          </Descriptions.Item>
        ) : null}
      </Descriptions>
      <Qualification lead={lead} />
      {lead.escalation ? (
        <div>
          <Typography.Text strong>{t.lead.escalation}</Typography.Text>
          <div>
            <EscalationReason escalation={lead.escalation} />
          </div>
        </div>
      ) : null}
    </Space>
  );
}

/** «Добавить заметку» прямо во вкладке — тот же диалог, что в меню «Ещё». */
function useAddNote(leadId: number) {
  const { run, busy } = useLeadActionRunner(leadId);
  const [open, setOpen] = useState(false);
  const dialog = (
    <LeadActionDialog
      key={open ? "note" : "closed"}
      dialog={open ? "note" : null}
      busy={busy}
      onClose={() => {
        setOpen(false);
      }}
      onRun={async (action) => {
        const ok = await run(action);
        if (ok) setOpen(false);
        return ok;
      }}
    />
  );
  return {
    dialog,
    start: () => {
      setOpen(true);
    },
  };
}

/** Вкладка «Заметки»: список и «Добавить заметку» (если есть право). */
export function LeadNotes({ leadId, canNote }: { leadId: number; canNote: boolean }) {
  const notes = useNotes(leadId);
  const add = useAddNote(leadId);
  const data = notes.data;
  const action = canNote ? { label: t.actions.note, onClick: add.start } : undefined;
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
  return (
    <>
      {data?.length ? (
        <List
          size="small"
          dataSource={data}
          footer={
            action ? (
              <Button type="link" size="small" icon={<PlusOutlined />} onClick={add.start}>
                {t.actions.note}
              </Button>
            ) : null
          }
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
      ) : (
        <EmptyState compact title={t.lead.notesEmpty} {...(action ? { action } : {})} />
      )}
      {canNote ? add.dialog : null}
    </>
  );
}
