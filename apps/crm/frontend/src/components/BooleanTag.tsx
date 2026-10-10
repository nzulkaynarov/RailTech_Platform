import { Tag } from "antd";
import type { ReactNode } from "react";

import { t } from "../i18n/ru";

type Props = { value: boolean | null | undefined; yes?: ReactNode; no?: ReactNode };

/** Признак «Да/Нет» тегом: «да» — зелёный, «нет» — нейтральный (Активен, Подтверждён и т. п.). */
export function BooleanTag({ value, yes = t.common.yes, no = t.common.no }: Props) {
  return value ? <Tag color="green">{yes}</Tag> : <Tag>{no}</Tag>;
}
