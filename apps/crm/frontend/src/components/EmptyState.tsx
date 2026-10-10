import { Button, Empty, Flex, Typography } from "antd";
import type { ReactNode } from "react";

export type EmptyStateAction = { label: ReactNode; onClick: () => void; icon?: ReactNode };

export type EmptyStateProps = {
  /** Что это: «Документов пока нет». */
  title: ReactNode;
  /** Почему пусто и что будет, когда появятся данные. */
  hint?: ReactNode;
  /** Необязательное главное действие (например, «Загрузить документ»). */
  action?: EmptyStateAction;
};

/** Единое пустое состояние поверх antd `Empty` (дизайн-аудит 2026-10-11, отчёт 4). */
export function EmptyState({ title, hint, action }: EmptyStateProps) {
  return (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={
        <Flex vertical gap="small" align="center">
          <Typography.Text strong>{title}</Typography.Text>
          {hint ? <Typography.Text type="secondary">{hint}</Typography.Text> : null}
        </Flex>
      }
    >
      {action ? (
        <Button type="primary" icon={action.icon} onClick={action.onClick}>
          {action.label}
        </Button>
      ) : null}
    </Empty>
  );
}
