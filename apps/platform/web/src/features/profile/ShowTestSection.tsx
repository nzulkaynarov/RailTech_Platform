import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Switch } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { Profile } from "../../shared/api/generated/model";
import { getGetProfileQueryKey, useUpdateProfile } from "../../shared/api/generated/platform-bff";
import { profileErrorText } from "./errors";
import { Section } from "./Section";

/**
 * «Показывать тестовые» (ТЕСТ-2): личная настройка, доступна любому сотруднику. Включено — тестовые компании и их документы
 * видны в работе с меткой «Тестовая»; выключено — скрыты, как у всех. Сохраняется сразу; после смены все списки читаются
 * заново, потому что сервер отдаёт другую выдачу.
 */
export function ShowTestSection({ profile }: { profile: Profile }) {
  const { t } = useTranslation("profile");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const labelId = useId();
  const update = useUpdateProfile({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetProfileQueryKey(), next);
        void message.success(t("showTest.saved"));
        // Выдача всех списков зависит от настройки: сбрасываем всё, кроме самого профиля.
        void queryClient.invalidateQueries({
          predicate: (query) => query.queryKey[0] !== getGetProfileQueryKey()[0],
        });
      },
    },
  });
  return (
    <Section title={t("showTest.title")} lead={t("showTest.hint")} testId="profile-show-test">
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Switch
          aria-labelledby={labelId}
          checked={profile.show_test ?? false}
          loading={update.isPending}
          onChange={(checked) => {
            update.mutate({ data: { show_test: checked } });
          }}
        />
        <span id={labelId}>{t("showTest.label")}</span>
      </div>
      {update.isError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={profileErrorText(t, "data", update.error)}
          style={{ marginTop: 12 }}
        />
      ) : null}
    </Section>
  );
}
