import { ApiOutlined, MailOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Descriptions,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import type { SmtpCheckOut, SmtpConnectorIn, SmtpStatusOut } from "../../api/generated/model";
import { SMTP_DEFAULT_PORT, SMTP_STATE_COLOR, smtpState } from "../../domain/integrations";
import { apiErrorMessage } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";

type Props = {
  status: SmtpStatusOut;
  saving: boolean;
  checking: boolean;
  testing: boolean;
  checkResult: SmtpCheckOut | null;
  checkError: unknown;
  onSave: (body: SmtpConnectorIn, done: () => void) => void;
  onCheck: () => void;
  onTestSend: () => void;
};

const S = t.integrations.smtp;
const SECURITY_OPTIONS = Object.entries(S.securities).map(([value, label]) => ({ value, label }));

/** Подпись пароля: «задан ••••last4» (из CRM), «задан в .env» или «не задан». */
function passwordHint(status: SmtpStatusOut): string {
  if (status.password_source === "db" && status.password_last4)
    return `${S.passwordSaved.replace("{last4}", status.password_last4)}. ${S.passwordKeep}`;
  if (status.password_source === "env") return S.passwordEnv;
  return S.passwordHint;
}

/** Итог «Проверить связь»: приветствие сервера, авторизация, время — или причина словами. */
function CheckResult({ result, error }: { result: SmtpCheckOut | null; error: unknown }) {
  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        role="status"
        message={S.checkFailed}
        description={apiErrorMessage(error)}
      />
    );
  }
  if (!result) return null;
  return (
    <Alert
      type="success"
      showIcon
      role="status"
      message={S.checkOk}
      description={
        <Descriptions column={1} size="small">
          <Descriptions.Item label={S.server}>{result.server || t.common.none}</Descriptions.Item>
          <Descriptions.Item label={S.username}>
            {result.authenticated ? S.checkAuth : S.checkNoAuth}
          </Descriptions.Item>
          <Descriptions.Item label={S.latency}>
            {S.latencyValue.replace("{ms}", String(result.latency_ms))}
          </Descriptions.Item>
        </Descriptions>
      }
    />
  );
}

function StatusSummary({ status }: { status: SmtpStatusOut }) {
  const state = smtpState(status);
  const source = t.tokenSource[status.settings_source] ?? status.settings_source;
  return (
    <Descriptions column={1} size="small">
      <Descriptions.Item label={S.status}>
        <Tag color={SMTP_STATE_COLOR[state]}>{S.state[state]}</Tag>
      </Descriptions.Item>
      <Descriptions.Item label={S.host}>
        {status.host ? (
          <>
            {status.host}:{status.port}{" "}
            <Typography.Text type="secondary">
              ({S.securities[status.security] ?? status.security}; {S.source}: {source})
            </Typography.Text>
          </>
        ) : (
          S.notSet
        )}
      </Descriptions.Item>
      <Descriptions.Item label={S.fromEmail}>
        {status.from_email
          ? status.from_name
            ? `${status.from_name} <${status.from_email}>`
            : status.from_email
          : S.notSet}
      </Descriptions.Item>
      <Descriptions.Item label={S.password}>
        {status.password_configured
          ? `${t.tokenSource[status.password_source] ?? status.password_source}${
              status.password_last4 ? ` ••••${status.password_last4}` : ""
            }`
          : S.notSet}
      </Descriptions.Item>
    </Descriptions>
  );
}

/**
 * Вкладка «Почта» (M3-CRM-08, ADR-0018): SMTP-релей для писем сотрудникам. Пароль только на
 * запись, сохранение — после пароля админа; «Проверить связь» без отправки; тестовое письмо —
 * в журнал и очередь.
 */
export function SmtpCard({
  status,
  saving,
  checking,
  testing,
  checkResult,
  checkError,
  onSave,
  onCheck,
  onTestSend,
}: Props) {
  const [host, setHost] = useState(status.host);
  const [port, setPort] = useState(status.port);
  const [security, setSecurity] = useState<SmtpStatusOut["security"]>(status.security);
  const [fromEmail, setFromEmail] = useState(status.from_email);
  const [fromName, setFromName] = useState(status.from_name);
  const [username, setUsername] = useState(status.username);
  const [secret, setSecret] = useState("");
  const [password, setPassword] = useState("");
  const [confirming, setConfirming] = useState(false);
  const close = () => {
    setConfirming(false);
    setPassword("");
  };
  const dirty =
    host.trim() !== status.host ||
    port !== status.port ||
    security !== status.security ||
    fromEmail.trim() !== status.from_email ||
    fromName.trim() !== status.from_name ||
    username.trim() !== status.username ||
    secret.trim().length > 0;
  return (
    <Flex vertical gap="middle">
      <Typography.Paragraph type="secondary">{S.intro}</Typography.Paragraph>
      <StatusSummary status={status} />
      {status.secrets_enabled ? null : (
        <Alert type="warning" showIcon message={S.secretsDisabled} />
      )}
      <Form
        layout="vertical"
        onFinish={() => {
          setConfirming(true);
        }}
      >
        <Form.Item label={S.host} htmlFor="smtp-host" extra={S.hostHint}>
          <Input
            id="smtp-host"
            autoComplete="off"
            value={host}
            placeholder={S.hostPlaceholder}
            onChange={(e) => {
              setHost(e.target.value);
            }}
          />
        </Form.Item>
        <Flex wrap gap="small">
          <Form.Item label={S.security} htmlFor="smtp-security" className="filter-md">
            <Select
              id="smtp-security"
              value={security}
              options={SECURITY_OPTIONS}
              onChange={(value: SmtpStatusOut["security"]) => {
                setSecurity(value);
                setPort(SMTP_DEFAULT_PORT[value]);
              }}
            />
          </Form.Item>
          <Form.Item label={S.port} htmlFor="smtp-port">
            <InputNumber
              id="smtp-port"
              min={1}
              max={65535}
              value={port}
              onChange={(value) => {
                setPort(value ?? status.port);
              }}
            />
          </Form.Item>
        </Flex>
        <Form.Item label={S.fromEmail} htmlFor="smtp-from-email" extra={S.fromEmailHint}>
          <Input
            id="smtp-from-email"
            type="email"
            inputMode="email"
            autoComplete="off"
            value={fromEmail}
            onChange={(e) => {
              setFromEmail(e.target.value);
            }}
          />
        </Form.Item>
        <Form.Item label={S.fromName} htmlFor="smtp-from-name">
          <Input
            id="smtp-from-name"
            autoComplete="off"
            value={fromName}
            onChange={(e) => {
              setFromName(e.target.value);
            }}
          />
        </Form.Item>
        <Form.Item label={S.username} htmlFor="smtp-username" extra={S.usernameHint}>
          <Input
            id="smtp-username"
            autoComplete="off"
            disabled={!status.secrets_enabled}
            value={username}
            onChange={(e) => {
              setUsername(e.target.value);
            }}
          />
        </Form.Item>
        <Form.Item label={S.password} htmlFor="smtp-password" extra={passwordHint(status)}>
          <Input.Password
            id="smtp-password"
            value={secret}
            autoComplete="off"
            disabled={!status.secrets_enabled}
            visibilityToggle={false}
            onChange={(e) => {
              setSecret(e.target.value);
            }}
          />
        </Form.Item>
        <Flex wrap gap="small">
          <Button type="primary" htmlType="submit" disabled={!dirty}>
            {S.save}
          </Button>
          <Button
            icon={<ApiOutlined aria-hidden />}
            loading={checking}
            disabled={!status.configured}
            onClick={onCheck}
          >
            {S.check}
          </Button>
          <Button
            icon={<MailOutlined aria-hidden />}
            loading={testing}
            disabled={!status.configured}
            onClick={onTestSend}
          >
            {S.testSend}
          </Button>
        </Flex>
      </Form>
      <CheckResult result={checkResult} error={checkError} />
      <Modal
        open={confirming}
        title={S.confirmTitle}
        okText={t.integrations.confirm}
        cancelText={t.integrations.cancel}
        okButtonProps={{ disabled: !password, loading: saving }}
        onCancel={close}
        onOk={() => {
          const body: SmtpConnectorIn = {
            host: host.trim(),
            port,
            security,
            from_email: fromEmail.trim(),
            from_name: fromName.trim(),
            username: username.trim() !== status.username ? username.trim() : null,
            smtp_password: secret.trim() || null,
            password,
          };
          onSave(body, () => {
            close();
            setSecret("");
          });
        }}
        destroyOnHidden
      >
        <Flex vertical gap="small">
          <Typography.Text type="secondary">{S.confirmHint}</Typography.Text>
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
