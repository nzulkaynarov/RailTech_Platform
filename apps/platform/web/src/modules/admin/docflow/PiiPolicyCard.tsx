import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Radio, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import {
  getGetDocflowSettingsQueryKey,
  useGetBotSettings,
  useGetDocflowSettings,
  useSaveBotSetting,
} from "../../../shared/api/generated/platform-bff";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { UnsavedGuard } from "../../../shared/ui/UnsavedGuard";
import { botErrorText } from "../bot/errors";
import { useRefreshBot } from "../bot/refresh";
import { POLICIES, type PiiPolicy, policyOf } from "./policy";

/**
 * Защита данных для ИИ (PD-BIZ, решение владельца 2026-11-03): выбор политики «Деловая» / «Строгая» с одним предложением
 * о том, что скрывается. Значение хранит CRM (раздел `ai` настроек), EDS получает его событием шины; сохранение пишется
 * в журнал аудита (кто, когда, было → стало). Меняет администратор, директор видит.
 */
export function PiiPolicyCard() {
  const { t } = useTranslation(["letters", "bot"]);
  const { me } = useAuth();
  const { message } = App.useApp();
  const editable = canEdit(me, "admin");
  const settings = useGetBotSettings();
  const refresh = useRefreshBot();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<PiiPolicy | null>(null);
  const docflow = useGetDocflowSettings();
  const saved = policyOf(settings.data?.values);
  // Фактическая политика документооборота (проекция по шине) отстаёт или не дошла — админ видит расхождение.
  const applied = docflow.data?.pii_policy;
  const lagging =
    settings.data !== undefined && applied !== undefined && applied !== saved ? applied : null;
  const value = draft ?? saved;
  const dirty = draft !== null && draft !== saved;

  const save = useSaveBotSetting({
    mutation: {
      onSuccess: async () => {
        await refresh();
        await queryClient.invalidateQueries({ queryKey: getGetDocflowSettingsQueryKey() });
        void message.success(
          t("letters:settings.ai.policy.saved", {
            name: t(`letters:settings.ai.policy.${value}`),
          }),
        );
        setDraft(null);
      },
    },
  });

  return (
    <section className="pf-pii pf-co-body" aria-labelledby="pf-pii-title">
      <UnsavedGuard when={dirty} busy={save.isPending} />
      <header className="pf-co-head">
        <h2 className="pf-co-title" id="pf-pii-title">
          {t("letters:settings.ai.policy.title")}
        </h2>
        <p className="pf-co-hint">{t("letters:settings.ai.policy.hint")}</p>
      </header>
      {settings.isPending ? <Skeleton active paragraph={{ rows: 2 }} title={false} /> : null}
      {settings.isError ? <ErrorNote message={botErrorText(t, settings.error)} /> : null}
      {settings.data ? (
        <>
          <Radio.Group
            className="pf-pii-options"
            value={value}
            disabled={!editable || save.isPending}
            aria-label={t("letters:settings.ai.policy.legend")}
            onChange={(event) => {
              setDraft(event.target.value as PiiPolicy);
            }}
          >
            {POLICIES.map((policy) => (
              <Radio key={policy} value={policy} className="pf-pii-option">
                <span className="pf-pii-name">{t(`letters:settings.ai.policy.${policy}`)}</span>
                <span className="pf-pii-text">{t(`letters:settings.ai.policy.${policy}Text`)}</span>
              </Radio>
            ))}
          </Radio.Group>
          <ErrorNote message={save.isError ? botErrorText(t, save.error) : null} />
          {lagging ? (
            <Alert
              type="warning"
              showIcon
              role="status"
              message={t("letters:settings.ai.policy.pending", {
                name: t(`letters:settings.ai.policy.${saved}`),
                current: t(`letters:settings.ai.policy.${lagging}`),
              })}
            />
          ) : null}
          {editable ? (
            <div className="pf-pii-actions">
              <span role="status">
                {dirty ? (
                  <StatusTag tone="gold">{t("bot:form.unsaved")}</StatusTag>
                ) : (
                  <span className="pf-hint">{t("bot:form.allSaved")}</span>
                )}
              </span>
              {dirty ? (
                <Button
                  onClick={() => {
                    setDraft(null);
                  }}
                >
                  {t("bot:form.discard")}
                </Button>
              ) : null}
              <Button
                type="primary"
                loading={save.isPending}
                disabled={!dirty}
                onClick={() => {
                  save.mutate({ key: "ai", data: { pii_policy: value } });
                }}
              >
                {t("bot:form.save")}
              </Button>
            </div>
          ) : (
            <p className="pf-hint">{t("letters:settings.ai.policy.readOnly")}</p>
          )}
        </>
      ) : null}
    </section>
  );
}
