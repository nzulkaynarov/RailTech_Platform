import { Tag } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  type StatusKind,
  type StatusTone,
  TONE_STYLE,
  isKnownStatus,
  statusLabelKey,
  statusTone,
} from "../lib/statuses";

export type StatusTagProps =
  | {
      /** Вид объекта и код статуса: слово и цвет берутся из карты SPEC-v3 §2.4 */
      kind: StatusKind;
      status: string;
      /** Своё слово вместо словарного (например, «Черновик · отправка заблокирована») */
      children?: ReactNode;
      tone?: never;
    }
  | {
      /** Произвольный тег: цвет и слово задаёт вызывающий (бейдж срока, «После отгрузки») */
      tone?: StatusTone;
      children: ReactNode;
      kind?: never;
      status?: never;
    };

/**
 * Статус словом и цветом (SPEC-v3 §5.2: статус не передаётся одним цветом, слово есть всегда). Тег antd 22 px, радиус 4,
 * шрифт 12; цвет текста — из колонки «текст» таблицы токенов, фон и рамка — светлые значения того же цвета
 * (03-frontend.md §3, §5). Неизвестный код статуса показывается как есть нейтральным тегом.
 */
export function StatusTag(props: StatusTagProps) {
  const { t } = useTranslation(["dictionary"]);
  let tone: StatusTone;
  let content: ReactNode = props.children;
  if (props.kind !== undefined) {
    tone = statusTone(props.kind, props.status);
    content ??= isKnownStatus(props.kind, props.status)
      ? t(statusLabelKey(props.kind, props.status))
      : props.status;
  } else {
    tone = props.tone ?? "default";
  }
  const style = TONE_STYLE[tone];
  return (
    <Tag bordered data-tone={tone} style={{ ...style, margin: 0, whiteSpace: "nowrap" }}>
      {content}
    </Tag>
  );
}
