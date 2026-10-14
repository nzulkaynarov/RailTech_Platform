/**
 * Вкладка «Ансамбль: CRM и ERP» на «Расходах» (M3-CRM-09, ARCHITECTURE §8): журнал шлюза LiteLLM —
 * всего за период, плитки систем с бюджетом на сегодня (превышение подсвечено), дни превышения,
 * таблица по дням с деградациями и разрезы по системе, функции и модели.
 */
import { Alert, Button, Card, Col, Flex, Row, Statistic, Tag, Typography } from "antd";
import { Link } from "react-router";

import type { AiSpendReport, AiSystemBudget } from "../../api/generated/model";
import { ApiError } from "../../api/http";
import { useAiSpend } from "../../api/spendQueries";
import { EmptyState } from "../../components/EmptyState";
import { PageState } from "../../components/PageState";
import {
  budgetText,
  erpNotConnected,
  isEmptyReport,
  overrunText,
  periodRange,
  systemLabel,
  systemTiles,
  usdPrecise,
} from "../../domain/aiSpend";
import { t } from "../../i18n/ru";
import { formatNumber } from "../../lib/format";
import { DayTable, Slices } from "./AiSpendTables";

const A = t.aiSpend;

function SystemTile({ s, notConnected }: { s: AiSystemBudget; notConnected: boolean }) {
  return (
    <Card size="small" title={systemLabel(s.system)} className="ai-spend-tile">
      <Flex vertical gap="small">
        <Statistic title={A.today} value={budgetText(s)} />
        <div role="status">
          {s.daily_usd > 0 && !notConnected ? (
            <Tag color={s.over_today ? "error" : "success"}>
              {s.over_today ? A.overBudget : A.withinBudget}
            </Tag>
          ) : null}
        </div>
        {notConnected ? (
          <div>
            <Typography.Text strong>{A.erpNotConnected}</Typography.Text>
            <Typography.Paragraph type="secondary" className="ai-spend-hint">
              {A.erpNotConnectedHint}
            </Typography.Paragraph>
          </div>
        ) : (
          <Typography.Text type="secondary">
            {A.period}: {usdPrecise(s.period_usd)} ·{" "}
            {A.calls.replace("{n}", formatNumber(s.period_calls))} ·{" "}
            <span title={A.degradedHint}>
              {A.fallbacks.replace("{n}", formatNumber(s.fallback_calls))}
            </span>
          </Typography.Text>
        )}
      </Flex>
    </Card>
  );
}

function Tiles({ report }: { report: AiSpendReport }) {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} md={8}>
        <Card size="small" title={A.total} className="ai-spend-tile">
          <Statistic value={usdPrecise(report.totals.cost_usd)} />
          <Typography.Text type="secondary">
            {A.calls.replace("{n}", formatNumber(report.totals.calls))} ·{" "}
            <span title={A.degradedHint}>
              {A.fallbacks.replace("{n}", formatNumber(report.totals.fallback_calls))}
            </span>
          </Typography.Text>
        </Card>
      </Col>
      {systemTiles(report).map((s) => (
        <Col xs={24} md={8} key={s.system}>
          <SystemTile s={s} notConnected={s.system === "erp" && erpNotConnected(report)} />
        </Col>
      ))}
    </Row>
  );
}

function Content({
  report,
  range,
}: {
  report: AiSpendReport;
  range: { from: string; to: string };
}) {
  return (
    <Flex vertical gap="middle">
      <Typography.Paragraph type="secondary">
        {A.source}{" "}
        <Link className="inline-link" to="/settings?section=budget">
          {A.budgetLink}
        </Link>
      </Typography.Paragraph>
      {report.truncated ? <Alert type="warning" showIcon message={A.truncated} /> : null}
      <Tiles report={report} />
      {report.overruns.length ? (
        <Alert
          type={report.systems.some((s) => s.over_today) ? "error" : "warning"}
          showIcon
          message={A.overruns}
          description={
            <ul className="ai-spend-overruns">
              {report.overruns.map((o) => (
                <li key={`${o.system}-${o.day}`}>{overrunText(o)}</li>
              ))}
            </ul>
          }
        />
      ) : null}
      {isEmptyReport(report) ? (
        <EmptyState title={A.empty} hint={A.emptyHint} />
      ) : (
        <>
          <DayTable report={report} />
          <Slices range={range} />
        </>
      )}
    </Flex>
  );
}

const gatewayDown = (error: unknown): boolean =>
  error instanceof ApiError && error.details.reason === "litellm_unavailable";

/** Период — последние `days` суток по Ташкенту (тот же переключатель, что у вкладки CRM). */
export function AiSpendPanel({ days }: { days: number }) {
  const range = periodRange(days);
  const query = useAiSpend(range, "day");
  if (query.isError && gatewayDown(query.error)) {
    return (
      <Alert
        type="warning"
        showIcon
        message={A.unavailable}
        description={A.unavailableHint}
        action={
          <Button size="small" onClick={() => void query.refetch()}>
            {t.state.retry}
          </Button>
        }
      />
    );
  }
  return (
    <PageState query={query} variant="section">
      {query.data ? <Content report={query.data} range={range} /> : null}
    </PageState>
  );
}
