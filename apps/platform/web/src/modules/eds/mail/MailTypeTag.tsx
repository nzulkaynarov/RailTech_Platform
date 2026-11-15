import {
  BanIcon,
  BankIcon,
  CalendarIcon,
  FileTextIcon,
  MailIcon,
  MegaphoneIcon,
  UsersIcon,
  WalletIcon,
} from "../../../shared/ui/lucide";
import { useTranslation } from "react-i18next";

import type { InboundMailType, InboundMailTypeIcon } from "../../../shared/api/generated/model";
import { DataTag } from "../../../shared/ui/DataTag";
import { localName } from "../dictionaries";

const ICONS: Record<InboundMailTypeIcon, typeof MailIcon> = {
  mail: MailIcon,
  team: UsersIcon,
  calendar: CalendarIcon,
  file: FileTextIcon,
  wallet: WalletIcon,
  bank: BankIcon,
  notification: MegaphoneIcon,
  stop: BanIcon,
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
