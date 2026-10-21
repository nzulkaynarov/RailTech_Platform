import { KeyOutlined, LinkOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Collapse, Descriptions, Flex, Form, Input, Modal, Typography } from "antd";
import { useState } from "react";

import type { ErpPairIn, ErpRotateIn, ErpStatusOut } from "../../api/generated/model";
import { apiErrorField, apiErrorMessage } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { formatDateTime } from "../../lib/time";

type Props = {
  status: ErpStatusOut;
  pairing: boolean;
  rotating: boolean;
  /** Ошибка последнего «Подключить»: подсвечивает поле кода или адреса. */
  pairError: unknown;
  onPair: (body: ErpPairIn, done: () => void) => void;
  onRotate: (body: ErpRotateIn, done: () => void) => void;
};

const P = t.integrations.erp.pairing;
const E = t.integrations.erp;

type Confirm = "pair" | "rotate" | null;

/** Ключ секрета для экрана: только «••••last4» или «—». */
function keyHint(last4: string | null | undefined): string {
  return last4 ? `••••${last4}` : E.notSet;
}

/**
 * «Подключить ERP» (M3-CRM-10): адрес + одноразовый код из ERP — остальное CRM делает сама. После сопряжения —
 * сводка ключей (без значений) и «Обновить ключи» без простоя. Пароль админа — в окне подтверждения.
 */
export function ErpPairing({ status, pairing, rotating, pairError, onPair, onRotate }: Props) {
  // Адрес подставлен внутренним адресом сервиса (compose): на свежем проде менять его не нужно.
  const [baseUrl, setBaseUrl] = useState(status.base_url || status.suggested_base_url || "");
  const [code, setCode] = useState("");
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [password, setPassword] = useState("");
  const close = () => {
    setConfirm(null);
    setPassword("");
  };
  const errorField = apiErrorField(pairError);
  /** Ошибка сопряжения у своего поля: подсветка и понятный текст (ADR-0017, `details.field`). */
  const fieldError = (field: string) =>
    errorField === field
      ? { validateStatus: "error" as const, help: apiErrorMessage(pairError) }
      : {};
  const pairForm = (
    <Form
      layout="vertical"
      onFinish={() => {
        setConfirm("pair");
      }}
    >
      <Form.Item
        label={E.baseUrl}
        htmlFor="erp-pair-base-url"
        extra={E.baseUrlHint}
        {...fieldError("base_url")}
      >
        <Input
          id="erp-pair-base-url"
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
        label={P.code}
        htmlFor="erp-pair-code"
        extra={status.bootstrap_available ? P.codeHint : P.codeRequired}
        {...fieldError("code")}
      >
        <Input
          id="erp-pair-code"
          autoComplete="off"
          spellCheck={false}
          value={code}
          placeholder={P.codePlaceholder}
          style={{ fontFamily: "monospace", letterSpacing: 1 }}
          onChange={(e) => {
            setCode(e.target.value);
          }}
        />
      </Form.Item>
      <Button
        type="primary"
        htmlType="submit"
        icon={<LinkOutlined aria-hidden />}
        disabled={
          !status.secrets_enabled ||
          !baseUrl.trim() ||
          (!code.trim() && !status.bootstrap_available)
        }
      >
        {P.connect}
      </Button>
    </Form>
  );

  return (
    <Flex vertical gap="middle">
      {status.paired ? (
        <>
          <Alert type="success" showIcon message={P.pairedTitle} description={P.pairedHint} />
          <Descriptions column={1} size="small">
            <Descriptions.Item label={P.keys.crmToErp}>
              {keyHint(status.token_last4)}
            </Descriptions.Item>
            <Descriptions.Item label={P.keys.erpToCrm}>
              {keyHint(status.inbound_token_last4)}
            </Descriptions.Item>
            <Descriptions.Item label={P.keys.webhook}>
              {keyHint(status.webhook_secret_last4)}
            </Descriptions.Item>
            {status.token_updated_at ? (
              <Descriptions.Item label={P.keysUpdated}>
                {formatDateTime(status.token_updated_at)}
              </Descriptions.Item>
            ) : null}
          </Descriptions>
          {status.rotation_pending ? (
            <Alert
              type="warning"
              showIcon
              role="status"
              message={P.rotationPendingTitle}
              description={P.rotationPending}
            />
          ) : null}
          {status.previous_secret_until ? (
            <Alert
              type="info"
              showIcon
              role="status"
              message={P.transition.replace("{time}", formatDateTime(status.previous_secret_until))}
            />
          ) : null}
          <Flex wrap gap="small">
            <Button
              icon={<ReloadOutlined aria-hidden />}
              loading={rotating}
              disabled={!status.secrets_enabled}
              onClick={() => {
                setConfirm("rotate");
              }}
            >
              {P.rotate}
            </Button>
          </Flex>
          <Collapse
            ghost
            items={[
              {
                key: "repair",
                label: P.repair,
                children: (
                  <Flex vertical gap="small">
                    <Typography.Paragraph type="secondary">{P.repairHint}</Typography.Paragraph>
                    {pairForm}
                  </Flex>
                ),
              },
            ]}
          />
        </>
      ) : (
        <>
          <Typography.Paragraph type="secondary">{P.intro}</Typography.Paragraph>
          <ol style={{ margin: 0, paddingInlineStart: 20 }}>
            {P.steps.map((step) => (
              <li key={step}>
                <Typography.Text>{step}</Typography.Text>
              </li>
            ))}
          </ol>
          {pairForm}
        </>
      )}
      <Modal
        open={confirm !== null}
        title={confirm === "rotate" ? P.rotateTitle : P.confirmTitle}
        okText={t.integrations.confirm}
        cancelText={t.integrations.cancel}
        okButtonProps={{
          disabled: !password,
          loading: pairing || rotating,
          icon: <KeyOutlined aria-hidden />,
        }}
        onCancel={close}
        onOk={() => {
          if (confirm === "rotate") {
            onRotate({ password }, close);
          } else {
            onPair({ base_url: baseUrl.trim(), code: code.trim() || null, password }, () => {
              close();
              setCode("");
            });
          }
        }}
        destroyOnHidden
      >
        <Flex vertical gap="small">
          <Typography.Text type="secondary">
            {confirm === "rotate" ? P.rotateHint : P.confirmHint}
          </Typography.Text>
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
