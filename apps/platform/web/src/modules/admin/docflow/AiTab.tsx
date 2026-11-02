import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Skeleton, Switch } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import {
  getGetDocflowSettingsQueryKey,
  useGetDocflowSettings,
  useUpdateDocflowSettings,
} from "../../../shared/api/generated/platform-bff";
import { TabHeader } from "../company/common";
import { dictionaryErrorText } from "./errors";

/**
 * Настройки · Документооборот · Распознавание (EDS-REG): «Заполнить из файла» в регистрации входящих. PDF с текстом
 * помощник читает всегда (персональные данные скрывает код до модели); сканы и фото — только если включено здесь
 * (по умолчанию выключено; решение юриста 2026-11-02). Переключатель сохраняется сразу, изменение — в журнале.
 */
export function AiTab({ readOnly }: { readOnly: boolean }) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const id = useId();
  const settings = useGetDocflowSettings();
  const update = useUpdateDocflowSettings({
    mutation: {
      onSuccess: (data) => {
        queryClient.setQueryData(getGetDocflowSettingsQueryKey(), data);
        void message.success(t("settings.ai.saved"));
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
          <div className="pf-docflow-switch">
            <Switch
              id={id}
              checked={settings.data.recognize_scans}
              disabled={readOnly}
              loading={update.isPending}
              aria-describedby={`${id}-hint`}
              onChange={(checked) => {
                update.mutate({ data: { recognize_scans: checked } });
              }}
            />
            <label htmlFor={id}>{t("settings.ai.scans")}</label>
          </div>
          <span className="pf-hint" id={`${id}-hint`}>
            {t("settings.ai.scansHint")}
          </span>
          {update.isError ? (
            <Alert
              type="error"
              showIcon
              role="alert"
              message={dictionaryErrorText(t, update.error)}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}
