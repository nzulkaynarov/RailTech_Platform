import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Skeleton, Switch } from "antd";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import {
  getGetDocflowSettingsQueryKey,
  useGetBotSettings,
  useGetDocflowSettings,
  useUpdateDocflowSettings,
} from "../../../shared/api/generated/platform-bff";
import { TabHeader } from "../company/common";
import { policyOf } from "./PiiPolicyCard";

/**
 * Настройки · Расходы на ИИ · «Заполнить из файла» (EDS-REG, PD-BIZ): помощник регистрации входящих. PDF с текстом
 * читается всегда, персональные данные скрывает код по политике «Защиты данных для ИИ». Сканы и фото — выбор
 * администратора (`recognize_scans`, по умолчанию включено) с подписью «Паспорта и личные документы не загружайте»;
 * при «Строгой» политике сканы выключены. Состояние показывается словами.
 */
export function AiTab() {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const { message } = App.useApp();
  const editable = canEdit(me, "admin");
  const queryClient = useQueryClient();
  const settings = useGetDocflowSettings();
  const bot = useGetBotSettings();
  const strict = policyOf(bot.data?.values) === "strict";
  const update = useUpdateDocflowSettings({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries({ queryKey: getGetDocflowSettingsQueryKey() });
        void message.success(t("settings.ai.scans.saved"));
      },
      onError: () => {
        void message.error(t("settings.ai.scans.error"));
      },
    },
  });

  return (
    <div className="pf-co-body">
      <TabHeader title={t("settings.ai.title")} hint={t("settings.ai.hint")} />
      {settings.isPending ? <Skeleton active paragraph={{ rows: 2 }} title={false} /> : null}
      {settings.isError ? (
        <Alert type="error" showIcon role="alert" message={t("settings.dict.errors.load")} />
      ) : null}
      {settings.data ? (
        <>
          {settings.data.ai_available ? null : (
            <Alert type="warning" showIcon message={t("settings.ai.off")} />
          )}
          <p className="pf-hint" style={{ margin: 0 }}>
            {t("settings.ai.text")}
          </p>
          <div className="pf-pii-scans">
            <Switch
              id="pf-scans-switch"
              checked={settings.data.recognize_scans && !strict}
              disabled={!editable || strict || update.isPending}
              loading={update.isPending}
              aria-labelledby="pf-scans-label"
              aria-describedby="pf-scans-hint"
              onChange={(checked) => {
                update.mutate({ data: { recognize_scans: checked } });
              }}
            />
            <div>
              <label id="pf-scans-label" htmlFor="pf-scans-switch" className="pf-pii-name">
                {t("settings.ai.scans.label")}
              </label>
              <p className="pf-hint" id="pf-scans-hint" style={{ margin: 0 }}>
                {strict ? t("settings.ai.scans.strict") : t("settings.ai.scans.hint")}
              </p>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
