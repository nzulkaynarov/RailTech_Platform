import { ReloadOutlined } from "@ant-design/icons";
import { Button, Card, List, Tag, Typography } from "antd";

import { useSystemStatus } from "../../api/adminQueries";
import type { ComponentStatusOut } from "../../api/generated/model";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { useNow } from "../../hooks/useNow";
import { t } from "../../i18n/ru";
import { fromNow } from "../../lib/time";

/** Цвет тега — пресеты Ant Design, они берут цвета из токенов темы (colorSuccess и т. д.). */
const TAG_COLOR: Record<ComponentStatusOut["status"], string> = {
  ok: "success",
  warn: "warning",
  fail: "error",
  unknown: "default",
};

export function StatusTag({ status }: { status: ComponentStatusOut["status"] }) {
  return <Tag color={TAG_COLOR[status]}>{t.system.status[status] ?? status}</Tag>;
}

function checkedText(at: string | null | undefined, now: Date): string {
  return at ? t.system.checkedAt.replace("{ago}", fromNow(at, now)) : t.system.neverChecked;
}

/** «Состояние системы» (admin): бот, канал, модели, очередь, бэкап, секреты — с причиной сбоя. */
export function SystemPage() {
  const query = useSystemStatus();
  const now = useNow();
  return (
    <PageBody>
      <PageHeader
        title={t.page.system}
        extra={
          <Button
            icon={<ReloadOutlined aria-hidden />}
            loading={query.isFetching}
            onClick={() => {
              void query.refetch();
            }}
          >
            {t.system.refresh}
          </Button>
        }
      />
      <PageState query={query}>
        {query.data ? (
          <Card>
            <Typography.Paragraph type="secondary">{t.system.hint}</Typography.Paragraph>
            <List
              dataSource={query.data.components}
              rowKey="key"
              renderItem={(c) => (
                <List.Item>
                  <List.Item.Meta
                    title={
                      <span>
                        <StatusTag status={c.status} /> {c.title}
                      </span>
                    }
                    description={
                      <>
                        {c.reason ? <div>{c.reason}</div> : null}
                        <Typography.Text type="secondary">
                          {checkedText(c.checked_at, now)}
                        </Typography.Text>
                      </>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        ) : null}
      </PageState>
    </PageBody>
  );
}
