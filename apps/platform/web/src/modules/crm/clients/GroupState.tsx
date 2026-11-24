import { useTranslation } from "react-i18next";

import type { TelegramGroupState } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";

/** Состояние группы с клиентом словом и цветом: в настройках канала и в карточке клиента одно и то же. */
export function GroupState({ state }: { state: TelegramGroupState }) {
  const { t } = useTranslation("clients");
  return (
    <StatusTag kind="tgGroup" status={state}>
      {t(`tgGroups.states.${state}`)}
    </StatusTag>
  );
}
