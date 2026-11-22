import { useQueryClient } from "@tanstack/react-query";
import { App, Switch } from "antd";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import {
  getGetDocflowSettingsQueryKey,
  useGetDocflowSettings,
  useUpdateDocflowSettings,
} from "../../../shared/api/generated/platform-bff";

/**
 * Правило письма «автор подписывает своё письмо» (ГЛ-0, ADR-0024 п. 3): настройка компании, по умолчанию включено.
 * Выключено — действует строгое «автор ≠ подписант» над тем же кругом, из которого выбирается подписант; если автор в круге
 * единственный, подписывает он. Показывается тем, кто читает настройки документооборота; переключает администратор.
 */
export function AuthorRule() {
  const { t } = useTranslation("signing");
  const { me } = useAuth();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const settings = useGetDocflowSettings();
  const update = useUpdateDocflowSettings({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries({ queryKey: getGetDocflowSettingsQueryKey() });
        void message.success(t("authorRule.saved"));
      },
      onError: () => {
        void message.error(t("authorRule.error"));
      },
    },
  });
  if (!settings.data) return null;
  return (
    <div className="pf-sign-rule">
      <Switch
        id="pf-author-rule-switch"
        checked={settings.data.author_may_sign_own_letter}
        disabled={!canEdit(me, "admin") || update.isPending}
        loading={update.isPending}
        aria-labelledby="pf-author-rule-label"
        aria-describedby="pf-author-rule-hint"
        onChange={(checked) => {
          update.mutate({ data: { author_may_sign_own_letter: checked } });
        }}
      />
      <div>
        <label
          id="pf-author-rule-label"
          htmlFor="pf-author-rule-switch"
          className="pf-sign-rule-name"
        >
          {t("authorRule.label")}
        </label>
        <p className="pf-hint" id="pf-author-rule-hint" style={{ margin: 0 }}>
          {settings.data.author_may_sign_own_letter ? t("authorRule.on") : t("authorRule.off")}
        </p>
      </div>
    </div>
  );
}
