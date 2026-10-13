import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import { Button, Tooltip, Typography } from "antd";
import { useEffect, useMemo } from "react";
import { useNavigate } from "react-router";

import { useInbox } from "../api/queries";
import { inboxQueue, isTextTarget, queueKeyAction, queuePosition } from "../domain/queue";
import { t } from "../i18n/ru";
import "../styles/workspace.css";

/**
 * «Предыдущий / следующий» по очереди «Входящих» прямо из карточки лида (бенчмарк Front,
 * Intercom: менеджер проходит очередь, не возвращаясь в список). Очередь — тот же запрос
 * инбокса, его обновляет SSE. Клавиши J/K — по коду клавиши, раскладка не важна.
 * Рендерить только тем, у кого есть доступ к «Входящим».
 */
export function QueueNav({ leadId }: { leadId: number }) {
  const inbox = useInbox();
  const navigate = useNavigate();
  const ids = useMemo(() => (inbox.data ? inboxQueue(inbox.data) : []), [inbox.data]);
  const pos = queuePosition(ids, leadId);
  const prevId = pos?.prevId ?? null;
  const nextId = pos?.nextId ?? null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const { code, altKey, ctrlKey, metaKey } = e;
      const inField = isTextTarget(e.target);
      const action = queueKeyAction({ code, altKey, ctrlKey, metaKey, inField });
      const target = action === "next" ? nextId : action === "prev" ? prevId : null;
      if (target === null) return;
      e.preventDefault();
      void navigate(`/leads/${String(target)}`);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [navigate, nextId, prevId]);

  if (!pos) return null;
  const go = (id: number | null) => () => {
    if (id !== null) void navigate(`/leads/${String(id)}`);
  };
  return (
    <nav className="queue-nav" aria-label={t.queue.label}>
      <Tooltip title={t.queue.keys}>
        <Button
          size="small"
          icon={<LeftOutlined aria-hidden />}
          aria-label={t.queue.prev}
          disabled={prevId === null}
          onClick={go(prevId)}
        />
      </Tooltip>
      <Typography.Text type="secondary">
        {t.queue.position
          .replace("{n}", String(pos.index + 1))
          .replace("{total}", String(pos.total))}
      </Typography.Text>
      <Tooltip title={t.queue.keys}>
        <Button
          size="small"
          icon={<RightOutlined aria-hidden />}
          aria-label={t.queue.next}
          disabled={nextId === null}
          onClick={go(nextId)}
        />
      </Tooltip>
    </nav>
  );
}
