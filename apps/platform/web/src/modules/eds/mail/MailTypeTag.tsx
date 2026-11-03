import {
  BankOutlined,
  CalendarOutlined,
  FileTextOutlined,
  MailOutlined,
  NotificationOutlined,
  StopOutlined,
  TeamOutlined,
  WalletOutlined,
} from "@ant-design/icons";
import type { ComponentType } from "react";
import { useTranslation } from "react-i18next";

import type { InboundMailType, InboundMailTypeIcon } from "../../../shared/api/generated/model";
import { DataTag } from "../../../shared/ui/DataTag";
import { localName } from "../dictionaries";

const ICONS: Record<InboundMailTypeIcon, ComponentType<{ "aria-hidden"?: boolean }>> = {
  mail: MailOutlined,
  team: TeamOutlined,
  calendar: CalendarOutlined,
  file: FileTextOutlined,
  wallet: WalletOutlined,
  bank: BankOutlined,
  notification: NotificationOutlined,
  stop: StopOutlined,
};

/** Тег типа письма: название на языке интерфейса, цвет и значок — данные справочника (закрытые наборы кода). */
export function MailTypeTag({ type }: { type: InboundMailType }) {
  const { i18n } = useTranslation();
  const Icon = ICONS[type.icon];
  return (
    <DataTag color={type.color}>
      <Icon aria-hidden /> {localName(type.name, i18n.language)}
    </DataTag>
  );
}
