import { Alert, Button, Card, Descriptions, Flex, Form, Input, Modal, Tag, Typography } from "antd";
import { useState } from "react";

import type { TelegramStatusOut, TelegramTokenIn } from "../../api/generated/model";
import { BOT_STATE_COLOR, botState } from "../../domain/integrations";
import { t } from "../../i18n/ru";

type Props = {
  status: TelegramStatusOut;
  saving: boolean;
  onSave: (body: TelegramTokenIn, done: () => void) => void;
};

/** Карточка бота: статус и поле токена только на запись; сохранение — после пароля. */
export function TelegramBotCard({ status, saving, onSave }: Props) {
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirming, setConfirming] = useState(false);
  const state = botState(status);
  const close = () => {
    setConfirming(false);
    setPassword("");
  };
  return (
    <Card title={t.integrations.botTitle}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label={t.integrations.botStatus}>
          <Tag color={BOT_STATE_COLOR[state]}>{t.botState[state]}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label={t.integrations.botUsername}>
          {status.username ? `@${status.username}` : t.common.none}
        </Descriptions.Item>
        <Descriptions.Item label={t.integrations.botMode}>
          {t.botMode[status.mode] ?? status.mode}
        </Descriptions.Item>
        <Descriptions.Item label={t.integrations.botSource}>
          {t.tokenSource[status.source] ?? status.source}
        </Descriptions.Item>
      </Descriptions>
      {status.secrets_enabled ? (
        <Form
          layout="vertical"
          onFinish={() => {
            setConfirming(true);
          }}
        >
          <Form.Item
            label={t.integrations.tokenLabel}
            htmlFor="bot-token"
            extra={
              status.last4
                ? t.integrations.tokenSaved.replace("{last4}", status.last4)
                : t.integrations.tokenHint
            }
          >
            <Input.Password
              id="bot-token"
              value={token}
              autoComplete="off"
              placeholder={t.integrations.tokenPlaceholder}
              visibilityToggle={false}
              onChange={(e) => {
                setToken(e.target.value);
              }}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" disabled={token.trim().length < 20}>
            {t.integrations.checkAndSave}
          </Button>
        </Form>
      ) : (
        <Alert type="warning" showIcon message={t.integrations.secretsDisabled} />
      )}
      <Modal
        open={confirming}
        title={t.integrations.confirmTitle}
        okText={t.integrations.confirm}
        cancelText={t.integrations.cancel}
        okButtonProps={{ disabled: !password, loading: saving }}
        onCancel={close}
        onOk={() => {
          onSave({ token: token.trim(), password }, () => {
            close();
            setToken("");
          });
        }}
        destroyOnHidden
      >
        <Flex vertical gap="small">
          <Typography.Text type="secondary">{t.integrations.confirmHint}</Typography.Text>
          <Input.Password
            aria-label={t.integrations.password}
            placeholder={t.integrations.password}
            autoComplete="current-password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
            }}
          />
        </Flex>
      </Modal>
    </Card>
  );
}
