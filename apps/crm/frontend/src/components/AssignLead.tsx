import { Button, Modal, Select } from "antd";
import { useState } from "react";

import type { LeadDetail } from "../api/generated/model";
import { type LeadAction, useTeam } from "../api/queries";
import { t } from "../i18n/ru";

type Props = { lead: LeadDetail; run: (action: LeadAction) => Promise<void>; busy: boolean };

/** «Передать коллеге» (ADR-0015): стадия не меняется, лид узнаёт имя нового менеджера. */
export function AssignLead({ lead, run, busy }: Props) {
  const [open, setOpen] = useState(false);
  const [userId, setUserId] = useState<number | null>(null);
  const team = useTeam();
  const options = (team.data ?? [])
    .filter((m) => m.id !== lead.assigned_user_id)
    .map((m) => ({ value: m.id, label: m.full_name }));
  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
        }}
      >
        {t.actions.assign}
      </Button>
      <Modal
        open={open}
        title={t.actions.assign}
        okText={t.actions.assign}
        cancelText={t.actions.cancel}
        confirmLoading={busy}
        okButtonProps={{ disabled: userId === null }}
        onOk={() => {
          if (userId !== null)
            void run({ kind: "assign", userId }).then(() => {
              setOpen(false);
            });
        }}
        onCancel={() => {
          setOpen(false);
        }}
        destroyOnHidden
      >
        <Select
          showSearch
          optionFilterProp="label"
          placeholder={t.actions.assignTo}
          style={{ width: "100%" }}
          value={userId}
          onChange={setUserId}
          options={options}
        />
      </Modal>
    </>
  );
}
