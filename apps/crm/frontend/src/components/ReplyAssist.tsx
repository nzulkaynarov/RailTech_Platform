import { EditOutlined, RobotOutlined, UndoOutlined } from "@ant-design/icons";
import { App as AntApp, Button, Space, Tooltip, Typography } from "antd";
import { useState } from "react";

import {
  type AssistMode,
  applyAssist,
  canAssist,
  needsReplaceConfirm,
} from "../domain/replyAssist";
import type { AssistRunner } from "../hooks/useReplyAssist";
import { t } from "../i18n/ru";

type Props = {
  draft: string;
  setDraft: (text: string) => void;
  runner: AssistRunner;
  disabled: boolean;
};

/** Кнопки «Черновик» и «Улучшить» у поля ответа (Q-019). Клиенту ничего не отправляют. */
export function ReplyAssist({ draft, setDraft, runner, disabled }: Props) {
  const { modal, message } = AntApp.useApp();
  // «Отменить» виден, пока в поле — результат «Улучшить» (после правки или отправки — нет).
  const [undo, setUndo] = useState<{ original: string; improved: string } | null>(null);
  const tt = t.lead.assist;

  const request = async (mode: AssistMode) => {
    const before = draft;
    const out = await runner.run(mode, before.trim());
    if (!out) return;
    const applied = applyAssist(mode, before, out);
    setDraft(applied.text);
    setUndo(applied.undo === null ? null : { original: applied.undo, improved: applied.text });
    void message.info(applied.info);
  };
  const onClick = (mode: AssistMode) => {
    if (!needsReplaceConfirm(mode, draft)) {
      void request(mode);
      return;
    }
    void modal.confirm({
      title: tt.replaceTitle,
      content: tt.replaceContent,
      okText: tt.replaceOk,
      cancelText: t.actions.cancel,
      onOk: () => request(mode),
    });
  };
  const busy = runner.pending !== null || disabled;

  return (
    <div className="chat-assist">
      <Space wrap size={[8, 4]}>
        <Tooltip title={tt.draftTip}>
          <Button
            size="small"
            icon={<RobotOutlined />}
            loading={runner.pending === "draft"}
            disabled={busy && runner.pending !== "draft"}
            onClick={() => {
              onClick("draft");
            }}
          >
            {tt.draft}
          </Button>
        </Tooltip>
        <Tooltip title={canAssist("improve", draft) ? tt.improveTip : tt.improveEmpty}>
          <Button
            size="small"
            icon={<EditOutlined />}
            loading={runner.pending === "improve"}
            disabled={!canAssist("improve", draft) || (busy && runner.pending !== "improve")}
            onClick={() => {
              onClick("improve");
            }}
          >
            {tt.improve}
          </Button>
        </Tooltip>
        {undo !== null && undo.improved === draft ? (
          <Tooltip title={tt.undoTip}>
            <Button
              size="small"
              type="link"
              icon={<UndoOutlined />}
              onClick={() => {
                setDraft(undo.original);
                setUndo(null);
              }}
            >
              {tt.undo}
            </Button>
          </Tooltip>
        ) : null}
      </Space>
      <Typography.Text type="secondary" className="chat-meta">
        {tt.cost}
      </Typography.Text>
    </div>
  );
}
