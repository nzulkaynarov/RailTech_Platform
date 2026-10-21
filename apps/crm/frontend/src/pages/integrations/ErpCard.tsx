import { ApiOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Checkbox,
  Descriptions,
  Flex,
  Form,
  Input,
  Modal,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import type { ErpCheckOut, ErpConnectorIn, ErpStatusOut } from "../../api/generated/model";
import { BooleanTag } from "../../components/BooleanTag";
import { ERP_STATE_COLOR, erpState } from "../../domain/integrations";
import { apiErrorMessage } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { formatDateTime } from "../../lib/time";

type Props = {
  status: ErpStatusOut;
  saving: boolean;
  checking: boolean;
  checkResult: ErpCheckOut | null;
  checkError: unknown;
  onSave: (body: ErpConnectorIn, done: () => void) => void;
  onCheck: () => void;
};

const E = t.integrations.erp;

/** Подпись секрета: «задан ••••last4» (из CRM), «задан в .env» или «не задан». */
function secretHint(
  source: ErpStatusOut["token_source"],
  last4: string | null,
  texts: { saved: string; env: string; hint: string },
): string {
  if (source === "db" && last4) return `${texts.saved.replace("{last4}", last4)}. ${E.tokenKeep}`;
  if (source === "env") return texts.env;
  return texts.hint;
}

/** Итог «Проверить связь»: версия, миграции, очередь, время ответа — или причина словами. */
function CheckResult({ result, error }: { result: ErpCheckOut | null; error: unknown }) {
  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        role="status"
        message={E.checkFailed}
        description={apiErrorMessage(error)}
      />
    );
  }
  if (!result) return null;
  if (result.status === "rate_limited") {
    // 429 ERP (шов 0.3.0): связь есть, частоту ограничили — статус, а не ошибка.
    return (
      <Alert
        type="info"
        showIcon
        role="status"
        message={E.checkRateLimited}
        description={E.checkRateLimitedHint.replace("{s}", String(result.retry_after_s ?? ""))}
      />
    );
  }
  const ok = result.status === "ok";
  return (
    <Alert
      type={ok ? "success" : "warning"}
      showIcon
      role="status"
      message={ok ? E.checkOk : E.checkDegraded}
      description={
        <Descriptions
          column={1}
          size="small"
          title={<span className="sr-only">{E.checkResult}</span>}
        >
          <Descriptions.Item label={E.version}>{result.version}</Descriptions.Item>
          <Descriptions.Item label={E.migrations}>
            <BooleanTag value={result.migrations_applied} />
          </Descriptions.Item>
          <Descriptions.Item label={E.queue}>
            <BooleanTag value={result.queue_alive} />
          </Descriptions.Item>
          <Descriptions.Item label={E.latency}>
            {E.latencyValue.replace("{ms}", String(result.latency_ms ?? ""))}
          </Descriptions.Item>
          <Descriptions.Item label={E.checkedAt}>
            {formatDateTime(result.checked_at)}
          </Descriptions.Item>
        </Descriptions>
      }
    />
  );
}

/**
 * Вкладка «ERP» (M3-CRM-02, ADR-0018): адрес, сервисный токен и секрет вебхуков только на запись,
 * сохранение — после пароля; «Проверить связь» ходит в `GET /api/integration/v1/health` ERP.
 */
export function ErpCard({
  status,
  saving,
  checking,
  checkResult,
  checkError,
  onSave,
  onCheck,
}: Props) {
  const [baseUrl, setBaseUrl] = useState(status.base_url);
  const [token, setToken] = useState("");
  const [webhook, setWebhook] = useState("");
  const [previous, setPrevious] = useState("");
  const [clearPrevious, setClearPrevious] = useState(false);
  const [password, setPassword] = useState("");
  const [confirming, setConfirming] = useState(false);
  const state = erpState(status);
  const close = () => {
    setConfirming(false);
    setPassword("");
  };
  const dirty =
    baseUrl.trim() !== status.base_url ||
    token.trim().length > 0 ||
    webhook.trim().length > 0 ||
    previous.trim().length > 0 ||
    clearPrevious;
  // «Снять предыдущий» имеет смысл, только пока он задан в CRM (из .env его не снять).
  const canClear = status.webhook_secret_previous_source === "db";
  return (
    <Flex vertical gap="middle">
      <Typography.Paragraph type="secondary">{E.intro}</Typography.Paragraph>
      <Descriptions column={1} size="small">
        <Descriptions.Item label={E.status}>
          <Tag color={ERP_STATE_COLOR[state]}>{E.state[state]}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label={E.mode}>{E.modes[status.mode] ?? status.mode}</Descriptions.Item>
        <Descriptions.Item label={E.baseUrl}>
          {status.base_url ? (
            <>
              {status.base_url}{" "}
              <Typography.Text type="secondary">
                ({E.source}: {t.tokenSource[status.base_url_source] ?? status.base_url_source})
              </Typography.Text>
            </>
          ) : (
            E.notSet
          )}
        </Descriptions.Item>
        <Descriptions.Item label={E.token}>
          {status.token_configured
            ? `${t.tokenSource[status.token_source] ?? status.token_source}${
                status.token_last4 ? ` ••••${status.token_last4}` : ""
              }`
            : E.notSet}
        </Descriptions.Item>
        <Descriptions.Item label={E.webhook}>
          {status.webhook_secret_configured
            ? `${t.tokenSource[status.webhook_secret_source] ?? status.webhook_secret_source}${
                status.webhook_secret_last4 ? ` ••••${status.webhook_secret_last4}` : ""
              }`
            : E.notSet}
        </Descriptions.Item>
        <Descriptions.Item label={E.webhookPrevious}>
          {status.webhook_secret_previous_configured
            ? `${
                t.tokenSource[status.webhook_secret_previous_source] ??
                status.webhook_secret_previous_source
              }${
                status.webhook_secret_previous_last4
                  ? ` ••••${status.webhook_secret_previous_last4}`
                  : ""
              }`
            : E.webhookPreviousNone}
        </Descriptions.Item>
      </Descriptions>
      {status.secrets_enabled ? null : (
        <Alert type="warning" showIcon message={E.secretsDisabled} />
      )}
      <Form
        layout="vertical"
        onFinish={() => {
          setConfirming(true);
        }}
      >
        <Form.Item label={E.baseUrl} htmlFor="erp-base-url" extra={E.baseUrlHint}>
          <Input
            id="erp-base-url"
            type="url"
            inputMode="url"
            autoComplete="off"
            value={baseUrl}
            placeholder={E.baseUrlPlaceholder}
            onChange={(e) => {
              setBaseUrl(e.target.value);
            }}
          />
        </Form.Item>
        <Form.Item
          label={E.token}
          htmlFor="erp-service-token"
          extra={secretHint(status.token_source, status.token_last4, {
            saved: E.tokenSaved,
            env: E.tokenEnv,
            hint: E.tokenHint,
          })}
        >
          <Input.Password
            id="erp-service-token"
            value={token}
            autoComplete="off"
            disabled={!status.secrets_enabled}
            visibilityToggle={false}
            onChange={(e) => {
              setToken(e.target.value);
            }}
          />
        </Form.Item>
        <Form.Item
          label={E.webhook}
          htmlFor="erp-webhook-secret"
          extra={secretHint(status.webhook_secret_source, status.webhook_secret_last4, {
            saved: E.webhookSaved,
            env: E.webhookEnv,
            hint: E.webhookHint,
          })}
        >
          <Input.Password
            id="erp-webhook-secret"
            value={webhook}
            autoComplete="off"
            disabled={!status.secrets_enabled}
            visibilityToggle={false}
            onChange={(e) => {
              setWebhook(e.target.value);
            }}
          />
        </Form.Item>
        <Form.Item
          label={E.webhookPrevious}
          htmlFor="erp-webhook-secret-previous"
          extra={
            status.webhook_secret_previous_source === "db" && status.webhook_secret_previous_last4
              ? `${E.webhookPreviousSaved.replace("{last4}", status.webhook_secret_previous_last4)}. ${E.webhookPreviousHint}`
              : status.webhook_secret_previous_source === "env"
                ? E.webhookPreviousEnv
                : E.webhookPreviousHint
          }
        >
          <Input.Password
            id="erp-webhook-secret-previous"
            value={previous}
            autoComplete="off"
            disabled={!status.secrets_enabled}
            visibilityToggle={false}
            onChange={(e) => {
              setPrevious(e.target.value);
              if (e.target.value) setClearPrevious(false);
            }}
          />
          {canClear ? (
            <Checkbox
              style={{ marginTop: 8 }}
              checked={clearPrevious}
              disabled={previous.trim().length > 0 || !status.secrets_enabled}
              onChange={(e) => {
                setClearPrevious(e.target.checked);
              }}
            >
              {E.webhookPreviousClear}
              <Typography.Text type="secondary"> — {E.webhookPreviousClearHint}</Typography.Text>
            </Checkbox>
          ) : null}
        </Form.Item>
        <Flex wrap gap="small">
          <Button type="primary" htmlType="submit" disabled={!dirty}>
            {E.save}
          </Button>
          <Button
            icon={<ApiOutlined aria-hidden />}
            loading={checking}
            disabled={!status.configured}
            onClick={onCheck}
          >
            {E.check}
          </Button>
        </Flex>
      </Form>
      <CheckResult result={checkResult} error={checkError} />
      <Modal
        open={confirming}
        title={E.confirmTitle}
        okText={t.integrations.confirm}
        cancelText={t.integrations.cancel}
        okButtonProps={{ disabled: !password, loading: saving }}
        onCancel={close}
        onOk={() => {
          const body: ErpConnectorIn = {
            base_url: baseUrl.trim(),
            service_token: token.trim() || null,
            webhook_secret: webhook.trim() || null,
            webhook_secret_previous: previous.trim() || null,
            clear_webhook_secret_previous: clearPrevious,
            password,
          };
          onSave(body, () => {
            close();
            setToken("");
            setWebhook("");
            setPrevious("");
            setClearPrevious(false);
          });
        }}
        destroyOnHidden
      >
        <Flex vertical gap="small">
          <Typography.Text type="secondary">{E.confirmHint}</Typography.Text>
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
    </Flex>
  );
}
