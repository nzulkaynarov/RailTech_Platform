import { Modal, Select } from "antd";
import { useState } from "react";

import type { LeadDetail } from "../api/generated/model";
import { type LeadAction, useTeam } from "../api/queries";
import { t } from "../i18n/ru";

type Props = {
  lead: LeadDetail;
  open: boolean;
  busy: boolean;
  onClose: () => void;
  run: (action: LeadAction) => Promise<boolean>;
};

/** «Переназначить» (ADR-0015): стадия не меняется, лид узнаёт имя нового менеджера. */
export function AssignLead({ lead, open, busy, onClose, run }: Props) {
  const [userId, setUserId] = useState<number | null>(null);
  const team = useTeam();
  const options = (team.data ?? [])
    .filter((m) => m.id !== lead.assigned_user_id)
    .map((m) => ({ value: m.id, label: m.full_name }));
  const submit = async () => {
    if (userId !== null && (await run({ kind: "assign", userId }))) onClose();
  };
  return (
    <Modal
      open={open}
      title={t.actions.assign}
      okText={t.actions.assign}
      cancelText={t.actions.cancel}
      confirmLoading={busy}
      okButtonProps={{ disabled: userId === null }}
      onOk={() => void submit()}
      onCancel={onClose}
      destroyOnHidden
    >
      <Select
        showSearch
        optionFilterProp="label"
        aria-label={t.actions.assignTo}
        placeholder={t.actions.assignTo}
        loading={team.isLoading}
        style={{ width: "100%" }}
        value={userId}
        onChange={setUserId}
        options={options}
      />
    </Modal>
  );
}
