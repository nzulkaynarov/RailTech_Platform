import { Tag } from "antd";
import type { ReactNode } from "react";

import { TAG_TEXT } from "../../app/theme";

export type StatusKind = "success" | "warning" | "error" | "default";

/**
 * Статус словом и цветом (SPEC-v3 §5.1: статус не передаётся одним цветом). Цвет текста — из колонки
 * «текст» таблицы токенов: затравочные цвета antd на фоне тега не проходят контраст 4.5:1.
 */
export function StatusTag({ kind, children }: { kind: StatusKind; children: ReactNode }) {
  return (
    <Tag color={kind} style={{ color: TAG_TEXT[kind] }}>
      {children}
    </Tag>
  );
}
