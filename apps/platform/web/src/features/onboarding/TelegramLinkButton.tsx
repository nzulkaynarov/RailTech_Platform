import { Button } from "antd";
import { useTranslation } from "react-i18next";

import { useTelegramLink } from "./useTelegramLink";

/** «Привязать Telegram» на пустой «Главной»: одна кнопка в пустом состоянии; привязан — её нет. */
export function TelegramLinkButton() {
  const { t } = useTranslation("help");
  const telegram = useTelegramLink();
  if (!telegram.show) return null;
  return (
    <>
      <Button loading={telegram.pending} onClick={telegram.start}>
        {t("welcome.telegram")}
      </Button>
      {telegram.error ? <span role="alert">{telegram.error}</span> : null}
    </>
  );
}
