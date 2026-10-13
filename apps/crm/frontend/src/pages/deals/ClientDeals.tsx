import { PlusOutlined } from "@ant-design/icons";
import { Button, Flex } from "antd";
import { useState } from "react";

import { useDeals } from "../../api/dealQueries";
import type { DealOut } from "../../api/generated/model";
import { PageState } from "../../components/PageState";
import { t } from "../../i18n/ru";
import { DealDialog } from "./DealDialog";
import { DealsTable } from "./DealsTable";

/** Вкладка «Сделки» на странице клиента: сделки клиента и «Новая сделка». */
export function ClientDeals({ clientId, canWrite }: { clientId: number; canWrite: boolean }) {
  const query = useDeals({ client_id: clientId });
  const [editing, setEditing] = useState<DealOut | null>(null);
  const [open, setOpen] = useState(false);
  const items = query.data ?? [];
  const create = () => {
    setEditing(null);
    setOpen(true);
  };
  return (
    <Flex vertical gap="small">
      {canWrite && items.length ? (
        <Button className="self-start" icon={<PlusOutlined />} onClick={create}>
          {t.deals.create}
        </Button>
      ) : null}
      <PageState
        query={query}
        variant="section"
        empty={
          !items.length && {
            compact: true,
            title: t.deals.clientEmpty,
            ...(canWrite ? { action: { label: t.deals.create, onClick: create } } : {}),
          }
        }
      >
        <DealsTable
          deals={items}
          embedded
          onEdit={
            canWrite
              ? (d) => {
                  setEditing(d);
                  setOpen(true);
                }
              : null
          }
        />
      </PageState>
      <DealDialog
        open={open}
        deal={editing}
        clientId={clientId}
        onClose={() => {
          setOpen(false);
        }}
      />
    </Flex>
  );
}
