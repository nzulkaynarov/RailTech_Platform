import { DesktopOutlined, SendOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import { channelLabel } from "./labels";

/**
 * Значок канала беседы (CHAT-1): Telegram — самолётик, «Кабинет» — экран кабинета клиента. Подпись — для диктора и
 * подсказкой при наведении; прочие каналы (сайт, звонок) значка не получают — у них нет переписки.
 */
export function ChannelMark({ channel }: { channel: string }) {
  const { t } = useTranslation("messages");
  if (channel !== "telegram" && channel !== "cabinet") return null;
  const label = t("list.channel", { channel: channelLabel(t, channel) });
  const Icon = channel === "cabinet" ? DesktopOutlined : SendOutlined;
  return (
    <span
      className={`pf-msg-channel pf-msg-channel--${channel}`}
      role="img"
      aria-label={label}
      title={label}
      data-channel={channel}
    >
      <Icon aria-hidden="true" />
    </span>
  );
}
