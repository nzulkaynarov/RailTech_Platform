import type { ReactNode } from "react";

import { type StatusTone, STATUS_TONES } from "../lib/statuses";
import { StatusTag } from "./StatusTag";

/**
 * Тег, цвет которого — данные администратора (тип письма, метка справочника), а не статус объекта. Цвет — из закрытого
 * набора тонов `StatusTone`; неизвестное значение — нейтральный. Цвет статуса модуль не выбирает (platform-frontend.md §5),
 * поэтому такой тег — здесь, в `shared`.
 */
export function DataTag({
  color,
  children,
  title,
}: {
  color: string;
  children: ReactNode;
  title?: string;
}) {
  const tone: StatusTone = (STATUS_TONES as readonly string[]).includes(color)
    ? (color as StatusTone)
    : "default";
  return title ? (
    <StatusTag tone={tone} title={title}>
      {children}
    </StatusTag>
  ) : (
    <StatusTag tone={tone}>{children}</StatusTag>
  );
}
