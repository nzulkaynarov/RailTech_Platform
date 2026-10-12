import { WarningOutlined } from "@ant-design/icons";
import { Button, Tag, Timeline, Tooltip, Typography } from "antd";
import { useState } from "react";

import type { DecisionsResponse } from "../api/generated/model";
import { aiText, eventText, splitDecisions, type QualifierRun } from "../domain/decisions";
import { decisionColor, decisionErrorLabel, reasonLabel } from "../domain/labels";
import { t } from "../i18n/ru";
import { formatWhen } from "../lib/time";
import { PageState } from "./PageState";

type Query = {
  data: DecisionsResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => unknown;
};

function When({ at }: { at: string }) {
  return <Typography.Text type="secondary">{formatWhen(at)}</Typography.Text>;
}

function AiBody({ item }: { item: QualifierRun }) {
  return (
    <div>
      <When at={item.at} />
      <div>{aiText(item)}</div>
      {item.triggers_fired.length ? (
        <div>
          {t.lead.triggers}:{" "}
          {item.triggers_fired.map((code) => (
            <Tag key={code}>{reasonLabel(code)}</Tag>
          ))}
        </div>
      ) : null}
      {item.next_best_action ? (
        <Typography.Text type="secondary">{item.next_best_action}</Typography.Text>
      ) : null}
    </div>
  );
}

/** Ошибки квалификатора — только админу, маленькой иконкой с подсказкой. */
function ErrorsHint({ errors }: { errors: QualifierRun[] }) {
  const last = errors[errors.length - 1];
  if (!last) return null;
  const label = t.lead.aiErrors.replace("{n}", String(errors.length));
  const tip = `${label}. ${decisionErrorLabel(last.error ?? "")} (${formatWhen(last.at)}). ${t.lead.decisionFailedHint}`;
  return (
    <Tooltip title={tip}>
      <Button type="text" size="small" icon={<WarningOutlined />} aria-label={tip} />
    </Tooltip>
  );
}

/**
 * «Почему система так решила» (SPEC §10.1): по умолчанию — смены стадий и передачи
 * словами; предложения ИИ свёрнуты под кнопкой. Ошибка запроса — `SectionError`.
 */
export function DecisionsPanel({ query, isAdmin }: { query: Query; isAdmin: boolean }) {
  const [showAi, setShowAi] = useState(false);
  const { events, ai, errors } = splitDecisions(query.data?.items ?? []);
  const empty = !events.length && !ai.length && !(isAdmin && errors.length);
  return (
    <PageState
      query={query}
      variant="section"
      empty={empty && { title: t.lead.noDecisions, hint: t.lead.noDecisionsHint }}
    >
      {isAdmin ? <ErrorsHint errors={errors} /> : null}
      {events.length ? (
        <Timeline
          items={events.map((item) => ({
            key: `transition-${String(item.id)}`,
            color: decisionColor(item.kind, false),
            children: (
              <div>
                <When at={item.at} />
                <div>{eventText(item)}</div>
              </div>
            ),
          }))}
        />
      ) : (
        <Typography.Paragraph type="secondary">{t.lead.noEvents}</Typography.Paragraph>
      )}
      {ai.length ? (
        <Button
          type="link"
          onClick={() => {
            setShowAi((v) => !v);
          }}
          aria-expanded={showAi}
        >
          {showAi ? t.lead.hideAi : t.lead.showAi.replace("{n}", String(ai.length))}
        </Button>
      ) : null}
      {showAi ? (
        <Timeline
          items={ai.map((item) => ({
            key: `qualifier-${String(item.id)}`,
            color: decisionColor(item.kind, item.escalated),
            children: <AiBody item={item} />,
          }))}
        />
      ) : null}
    </PageState>
  );
}
