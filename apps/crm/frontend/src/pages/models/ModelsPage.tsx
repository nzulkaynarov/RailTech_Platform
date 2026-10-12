import { App as AntApp, Button, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { ModelStatus } from "../../api/generated/model";
import { useModels, useTestModel } from "../../api/spendQueries";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { healthLabel, roleLabel, usd } from "../../domain/spend";
import { t } from "../../i18n/ru";
import { useNow } from "../../hooks/useNow";
import { fromNow } from "../../lib/time";
import "../admin.css";

const HEALTH_COLOR: Record<string, string> = {
  ok: "success",
  problem: "error",
  unknown: "default",
};

function useCheck() {
  const { modal, message } = AntApp.useApp();
  const test = useTestModel();
  return (alias: string) => {
    const role = roleLabel(alias);
    modal.confirm({
      title: t.models.confirmTitle,
      content: t.models.confirmText.replace("{role}", role),
      okText: t.models.confirmOk,
      onOk: async () => {
        const result = await test.mutateAsync(alias);
        if (result.ok) {
          void message.success(
            t.models.ok.replace("{role}", role).replace("{ms}", String(result.latency_ms)),
          );
        } else {
          void message.error(
            t.models.failed.replace("{role}", role).replace("{detail}", result.detail ?? ""),
          );
        }
      },
    });
  };
}

function columns(check: (alias: string) => void, now: Date): ColumnsType<ModelStatus> {
  return [
    {
      title: t.models.role,
      dataIndex: "alias",
      render: (v: string, r) => (
        <div>
          <div>{roleLabel(v)}</div>
          <Typography.Text type="secondary" className="model-id">
            {[r.provider ?? t.models.unknownProvider, r.model].filter(Boolean).join(" · ")}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: t.models.status,
      dataIndex: "health",
      render: (v: string, r) => (
        <div className="model-health">
          <Tag color={HEALTH_COLOR[v] ?? "default"}>{healthLabel(v)}</Tag>
          {r.health_detail ? (
            <Tooltip title={r.health_detail}>
              <Typography.Text type="danger" ellipsis className="model-error">
                {r.health_detail}
              </Typography.Text>
            </Tooltip>
          ) : null}
        </div>
      ),
    },
    {
      title: t.models.checkedAt,
      dataIndex: "checked_at",
      responsive: ["md"],
      render: (v: string | null) => (v ? fromNow(v, now) : "—"),
    },
    { title: t.models.todaySpend, dataIndex: "today_usd", align: "right", render: usd },
    {
      title: t.common.actions,
      key: "check",
      render: (_, r) => (
        <Button
          size="small"
          aria-label={t.models.checkAria.replace("{role}", roleLabel(r.alias))}
          onClick={() => {
            check(r.alias);
          }}
        >
          {t.models.check}
        </Button>
      ),
    },
  ];
}

/** «Модели ИИ» (админ, только просмотр): роль → провайдер, модель, состояние, расход; проверка. */
export function ModelsPage() {
  const query = useModels();
  const check = useCheck();
  const now = useNow();
  return (
    <PageBody>
      <PageHeader title={t.page.models} />
      <Typography.Paragraph type="secondary">
        {t.models.hint} {t.models.checkedHint}
      </Typography.Paragraph>
      <PageState query={query}>
        <Table
          rowKey="alias"
          size="small"
          pagination={false}
          scroll={{ x: 720 }}
          dataSource={query.data ?? []}
          columns={columns(check, now)}
        />
      </PageState>
    </PageBody>
  );
}
