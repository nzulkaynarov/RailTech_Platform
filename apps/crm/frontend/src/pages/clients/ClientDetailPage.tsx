import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  App as AntApp,
  Button,
  Card,
  Descriptions,
  InputNumber,
  List,
  Popconfirm,
  Space,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { adminKeys, useClient } from "../../api/adminQueries";
import { linkTelegram, unlinkTelegram } from "../../api/generated/crm";
import type { IdentityOut } from "../../api/generated/model";
import { type ApiError, unwrap } from "../../api/http";
import { usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { StageBadge } from "../../components/StageBadge";
import { errorText, t } from "../../i18n/ru";
import { ClientDocuments } from "./ClientDocuments";
import { ServiceRequests } from "./ServiceRequests";

type Action = { kind: "link" | "unlink"; tgUserId: number };

function identityLabel(i: IdentityOut): string {
  const name = i.tg_username ? `@${i.tg_username}` : (i.tg_first_name ?? "");
  return `${name} · ${String(i.tg_user_id)}`;
}

/** Карточка клиента (SPEC §10.1, §7.3): Telegram с подтверждением, лиды, документы, запросы. */
export function ClientDetailPage() {
  const id = Number(useParams()["id"]);
  const { data } = useClient(id);
  const perms = usePermissionsQuery();
  const canWrite = allowed(perms.data, "clients", "write");
  const canDocs = allowed(perms.data, "documents", "read");
  const [tgId, setTgId] = useState<number | null>(null);
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const act = useMutation({
    mutationFn: async (a: Action) => {
      if (a.kind === "link") return unwrap(await linkTelegram(id, { tg_user_id: a.tgUserId }));
      return unwrap(await unlinkTelegram(id, a.tgUserId));
    },
    onSuccess: () => {
      setTgId(null);
      void client.invalidateQueries({ queryKey: adminKeys.client(id) });
    },
    onError: (e) => {
      void message.error(errorText((e as ApiError).code, e.message));
    },
  });
  if (!data) return <Card loading />;

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Typography.Title level={4} style={{ margin: 0 }}>
        {data.name}
      </Typography.Title>
      <Descriptions size="small" column={{ xs: 1, md: 3 }}>
        <Descriptions.Item label={t.clients.inn}>{data.inn ?? t.common.none}</Descriptions.Item>
        <Descriptions.Item label={t.clients.segment}>
          {data.segment ?? t.common.none}
        </Descriptions.Item>
        <Descriptions.Item label={t.clients.active}>
          {data.is_active ? t.common.yes : t.common.no}
        </Descriptions.Item>
      </Descriptions>
      <Card
        size="small"
        title={t.clients.telegram}
        extra={<Typography.Text type="secondary">{t.clients.telegramHint}</Typography.Text>}
      >
        <List
          size="small"
          dataSource={data.identities}
          renderItem={(i) => (
            <List.Item
              actions={
                canWrite
                  ? [
                      <Popconfirm
                        key="u"
                        title={t.clients.unlink}
                        onConfirm={() => {
                          act.mutate({ kind: "unlink", tgUserId: i.tg_user_id });
                        }}
                      >
                        <Button size="small" danger>
                          {t.clients.unlink}
                        </Button>
                      </Popconfirm>,
                    ]
                  : []
              }
            >
              {identityLabel(i)}{" "}
              {i.verified_at ? (
                <Tag color="green">
                  {t.clients.verified} {dayjs(i.verified_at).format("DD.MM.YY")}
                </Tag>
              ) : null}
            </List.Item>
          )}
        />
        {canWrite && data.candidates.length ? (
          <List
            size="small"
            header={t.clients.candidates}
            dataSource={data.candidates}
            renderItem={(i) => (
              <List.Item
                actions={[
                  <Button
                    key="l"
                    size="small"
                    type="primary"
                    onClick={() => {
                      act.mutate({ kind: "link", tgUserId: i.tg_user_id });
                    }}
                  >
                    {t.clients.link}
                  </Button>,
                ]}
              >
                {identityLabel(i)}
              </List.Item>
            )}
          />
        ) : null}
        {canWrite ? (
          <Space.Compact style={{ marginTop: 8 }}>
            <InputNumber
              placeholder={t.clients.tgId}
              style={{ width: 240 }}
              min={1}
              value={tgId}
              onChange={setTgId}
            />
            <Button
              disabled={tgId === null}
              onClick={() => {
                if (tgId !== null) act.mutate({ kind: "link", tgUserId: tgId });
              }}
            >
              {t.clients.link}
            </Button>
          </Space.Compact>
        ) : null}
      </Card>
      <Card size="small" title={t.clients.leads}>
        <List
          size="small"
          dataSource={data.leads}
          renderItem={(lead) => (
            <List.Item>
              <Link to={`/leads/${String(lead.id)}`}>
                #{lead.id} · {lead.display_name}
              </Link>{" "}
              <StageBadge stage={lead.stage} />
            </List.Item>
          )}
        />
      </Card>
      {canDocs ? (
        <Card size="small" title={t.clients.documents}>
          <ClientDocuments clientId={id} canWrite={allowed(perms.data, "documents", "write")} />
        </Card>
      ) : null}
      <Card size="small" title={t.clients.requests}>
        <ServiceRequests clientId={id} requests={data.service_requests} canWrite={canWrite} />
      </Card>
    </Space>
  );
}
