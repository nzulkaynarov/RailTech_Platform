import { PlusOutlined } from "@ant-design/icons";
import { Button, Card, Select, Space } from "antd";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { useDeals } from "../../api/dealQueries";
import type { DealOut } from "../../api/generated/model";
import { usePermissionsQuery, useTeam } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { stageFromSearch, stageLabel } from "../../domain/deals";
import { t } from "../../i18n/ru";
import { DealDialog } from "./DealDialog";
import { DealsTable } from "./DealsTable";
import "../pages.css";

const STAGES = ["open", "won", "lost"] as const;

/** Раздел «Сделки» (Q-013, SPEC §10.1): фильтр по стадии и ответственному, `?stage=` в адресе. */
export function DealsPage() {
  const [search, setSearch] = useSearchParams();
  const stage = stageFromSearch(search.get("stage"));
  const owner = Number(search.get("owner")) || undefined;
  const query = useDeals({
    ...(stage ? { stage } : {}),
    ...(owner ? { owner_user_id: owner } : {}),
  });
  const team = useTeam();
  const perms = usePermissionsQuery();
  const canWrite = allowed(perms.data, "deals", "write");
  const [editing, setEditing] = useState<DealOut | null>(null);
  const [open, setOpen] = useState(false);
  const setParam = (key: string, value: string | number | undefined) => {
    const next = new URLSearchParams(search);
    if (value === undefined) next.delete(key);
    else next.set(key, String(value));
    setSearch(next, { replace: true });
  };
  const items = query.data ?? [];
  const create = () => {
    setEditing(null);
    setOpen(true);
  };
  return (
    <PageBody>
      <PageHeader
        title={t.page.deals}
        extra={
          canWrite ? (
            <Button type="primary" icon={<PlusOutlined />} onClick={create}>
              {t.deals.create}
            </Button>
          ) : null
        }
      />
      <Space wrap>
        <Select
          aria-label={t.deals.stage}
          style={{ width: 176 }}
          allowClear
          placeholder={t.deals.stage}
          value={stage}
          onChange={(v: string | undefined) => {
            setParam("stage", v);
          }}
          options={STAGES.map((s) => ({ value: s, label: stageLabel(s) }))}
        />
        <Select
          aria-label={t.deals.owner}
          style={{ width: 176 }}
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder={t.deals.owner}
          value={owner}
          onChange={(v: number | undefined) => {
            setParam("owner", v);
          }}
          options={(team.data ?? []).map((m) => ({ value: m.id, label: m.full_name }))}
        />
      </Space>
      <PageState
        query={query}
        empty={
          !items.length && {
            title: t.deals.empty,
            hint: t.deals.emptyHint,
            ...(canWrite && !stage && !owner
              ? { action: { label: t.deals.create, onClick: create } }
              : {}),
          }
        }
      >
        <Card size="small">
          <DealsTable
            deals={items}
            onEdit={
              canWrite
                ? (d) => {
                    setEditing(d);
                    setOpen(true);
                  }
                : null
            }
          />
        </Card>
      </PageState>
      <DealDialog
        open={open}
        deal={editing}
        onClose={() => {
          setOpen(false);
        }}
      />
    </PageBody>
  );
}
