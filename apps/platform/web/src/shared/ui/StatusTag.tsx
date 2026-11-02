import { Tag } from "antd";
import { type ReactNode, useLayoutEffect, useRef } from "react";
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
      /** Полный текст для подсказки, когда `children` — разметка (обрезанный в узкой колонке тег) */
      title?: string;
      tone?: never;
    }
  | {
      /** Произвольный тег: цвет и слово задаёт вызывающий (бейдж срока, «После отгрузки») */
      tone?: StatusTone;
      children: ReactNode;
      title?: string;
      kind?: never;
      status?: never;
    };

/** Текст тега для подсказки: строки и числа (в том числе списком, как «Оплачена · 01.11.2026»); разметка — без подсказки. */
function plainText(node: ReactNode): string | undefined {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (!Array.isArray(node)) return undefined;
  const parts = (node as readonly ReactNode[]).map((part) =>
    part === null || part === undefined || part === false ? "" : plainText(part),
  );
  return parts.every((part) => part !== undefined) ? parts.join("") : undefined;
}

/**
 * Статус словом и цветом (SPEC-v3 §5.2: статус не передаётся одним цветом, слово есть всегда). Тег antd 22 px, радиус 4,
 * шрифт 12; цвет текста — из колонки «текст» таблицы токенов, фон и рамка — светлые значения того же цвета
 * (docs/architecture/platform-frontend.md §3, §5). Неизвестный код статуса показывается как есть нейтральным тегом.
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
  const full = props.title ?? plainText(content);
  const ref = useRef<HTMLSpanElement>(null);
  // Подсказка — только у обрезанного тега: колонки таблиц фиксированы, поэтому достаточно проверить после отрисовки.
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (full && element.scrollWidth > element.clientWidth) element.title = full;
    else element.removeAttribute("title");
  });
  // В узкой колонке таблицы тег обрезается многоточием (platform-frontend.md §4.2): полный текст — в подсказке.
  return (
    <Tag ref={ref} bordered data-tone={tone} style={{ ...style, margin: 0, whiteSpace: "nowrap" }}>
      {content}
    </Tag>
  );
}
