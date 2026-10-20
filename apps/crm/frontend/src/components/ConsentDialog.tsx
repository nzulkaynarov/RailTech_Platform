import { Input, Modal, Radio, Space, Typography } from "antd";
import { useState } from "react";

import type { ConsentRecordMethod } from "../api/generated/model";
import type { LeadAction } from "../api/queries";
import { t } from "../i18n/ru";

const METHODS: readonly ConsentRecordMethod[] = ["phone", "email", "paper"];

type Props = {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onRun: (action: LeadAction) => Promise<boolean>;
};

/**
 * «Согласие получено» (D-8): сотрудник отмечает, как лид, заведённый вручную, дал согласие на
 * обработку данных. Монтируется заново при каждом открытии (`key` у родителя).
 */
export function ConsentDialog({ open, busy, onClose, onRun }: Props) {
  const [method, setMethod] = useState<ConsentRecordMethod>("phone");
  const [comment, setComment] = useState("");
  const text = t.actions.consentDialog;
  return (
    <Modal
      open={open}
      title={t.actions.recordConsent}
      okText={t.actions.recordConsent}
      cancelText={t.actions.cancel}
      confirmLoading={busy}
      onOk={() => {
        void onRun({ kind: "consent", method, comment: comment.trim() || null });
      }}
      onCancel={onClose}
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          {text.hint}
        </Typography.Paragraph>
        <div role="radiogroup" aria-labelledby="consent-method-label">
          <Typography.Text strong id="consent-method-label">
            {text.method}
          </Typography.Text>
          <Radio.Group
            style={{ display: "block", marginTop: 8 }}
            value={method}
            onChange={(e) => {
              setMethod(e.target.value as ConsentRecordMethod);
            }}
          >
            <Space direction="vertical">
              {METHODS.map((m) => (
                <Radio key={m} value={m}>
                  {text.methods[m]}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </div>
        <Input.TextArea
          aria-label={text.comment}
          placeholder={text.commentPlaceholder}
          maxLength={500}
          autoSize={{ minRows: 2, maxRows: 4 }}
          value={comment}
          onChange={(e) => {
            setComment(e.target.value);
          }}
        />
      </Space>
    </Modal>
  );
}
