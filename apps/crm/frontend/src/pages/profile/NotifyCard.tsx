import { SendOutlined } from "@ant-design/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, App as AntApp, Button, Card, Flex, Switch, Typography } from "antd";
import type { ReactNode } from "react";

import { testNotification, updateMe } from "../../api/generated/crm";
import type { MePatch, UserOut } from "../../api/generated/model";
import { unwrap } from "../../api/http";
import { keys } from "../../api/queries";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useBrowserAlertsPref } from "../../hooks/useLeadAlerts";
import { t } from "../../i18n/ru";
import { formatDateTime } from "../../lib/time";

/** Поле может добавить бэкенд (неудачная доставка личного сообщения); читаем необязательно. */
type WithDmFailure = UserOut & { tg_dm_failed_at?: string | null };

function Row({
  id,
  label,
  hint,
  control,
}: {
  id: string;
  label: string;
  hint: string;
  control: ReactNode;
}) {
  return (
    <Flex justify="space-between" align="start" gap="middle">
      <div>
        <label htmlFor={id}>{label}</label>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {hint}
        </Typography.Paragraph>
      </div>
      {control}
    </Flex>
  );
}

/** Подписки на личные сообщения от бота (Q-010) и звук/уведомления браузера. */
export function NotifyCard({ user }: { user: UserOut }) {
  const client = useQueryClient();
  const onError = useApiErrorToast();
  const { message } = AntApp.useApp();
  const browser = useBrowserAlertsPref();
  const save = useMutation({
    mutationFn: async (patch: MePatch) => unwrap(await updateMe(patch)),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.me }),
    onError,
  });
  const test = useMutation({
    mutationFn: async () => unwrap(await testNotification()),
    onSuccess: () => void message.success(t.notify.testSent),
    onError,
  });
  const isAdmin = user.roles.includes("admin");
  const linked = user.tg_user_id !== null;
  const dmFailedAt = (user as WithDmFailure).tg_dm_failed_at ?? null;
  return (
    <Card title={t.notify.title}>
      <Flex vertical gap="middle">
        {!linked ? <Alert type="info" showIcon message={t.profileUi.linkTelegramFirst} /> : null}
        {linked && dmFailedAt ? (
          <Alert
            type="warning"
            showIcon
            message={t.profileUi.dmFailed.replace("{time}", formatDateTime(dmFailedAt))}
          />
        ) : null}
        {isAdmin ? (
          <Row
            id="notify-system"
            label={t.notify.system}
            hint={t.notify.systemHint}
            control={
              <Switch
                id="notify-system"
                checked={user.notify_system}
                disabled={!linked}
                loading={save.isPending}
                onChange={(v) => {
                  save.mutate({ notify_system: v });
                }}
              />
            }
          />
        ) : null}
        <Row
          id="notify-leads"
          label={t.notify.leads}
          hint={t.notify.leadsHint}
          control={
            <Switch
              id="notify-leads"
              checked={user.notify_leads}
              disabled={!linked}
              loading={save.isPending}
              onChange={(v) => {
                save.mutate({ notify_leads: v });
              }}
            />
          }
        />
        <Typography.Text type="secondary">{t.notify.botHint}</Typography.Text>
        <div>
          <Button
            icon={<SendOutlined aria-hidden />}
            disabled={!linked}
            loading={test.isPending}
            onClick={() => {
              test.mutate();
            }}
          >
            {t.notify.test}
          </Button>
        </div>
        <Row
          id="notify-browser"
          label={t.notify.browser}
          hint={browser.denied ? t.notify.browserDenied : t.notify.browserHint}
          control={
            <Switch
              id="notify-browser"
              checked={browser.enabled}
              onChange={(v) => {
                void browser.toggle(v);
              }}
            />
          }
        />
      </Flex>
    </Card>
  );
}
