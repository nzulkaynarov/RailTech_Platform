import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, QRCode, Space, Typography } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../shared/api/errors";
import {
  getGetSecondFactorQueryKey,
  useDisableSecondFactor,
  useEnableSecondFactor,
  useGetSecondFactor,
  useSetupSecondFactor,
} from "../../shared/api/generated/platform-bff";
import type { SecondFactorSetup } from "../../shared/api/generated/model";
import { useFormat } from "../../shared/lib/useFormat";
import { Dialog } from "../../shared/ui/Dialog";
import { BackupCodes } from "./BackupCodes";
import { Section } from "./Section";

/** Текст отказа по `details.reason` (CRM) — иначе общий. */
function reasonText(t: (key: string) => string, error: unknown): string {
  const reason =
    error instanceof ApiError && typeof error.details["reason"] === "string"
      ? error.details["reason"]
      : "";
  const known = [
    "second_factor_code_invalid",
    "second_factor_already_enabled",
    "second_factor_required",
    "secrets_key_missing",
  ];
  return t(`secondFactor.errors.${known.includes(reason) ? reason : "default"}`);
}

/**
 * Второй фактор входа (ДВ-4, реестр рисков Д1): код из приложения-аутентификатора. Включение в два шага — QR-код и
 * код подтверждения, затем резервные коды (показываются один раз). Отключение — кодом.
 */
export function SecondFactorSection() {
  const { t } = useTranslation("profile");
  const { date } = useFormat();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const status = useGetSecondFactor();
  const [setup, setSetup] = useState<SecondFactorSetup | null>(null);
  const [backup, setBackup] = useState<string[] | null>(null);
  const [disabling, setDisabling] = useState(false);
  const [code, setCode] = useState("");
  const codeId = useId();
  const refresh = () => queryClient.invalidateQueries({ queryKey: getGetSecondFactorQueryKey() });

  const start = useSetupSecondFactor({ mutation: { onSuccess: setSetup } });
  const enable = useEnableSecondFactor({
    mutation: {
      onSuccess: (result) => {
        setSetup(null);
        setCode("");
        setBackup(result.backup_codes);
        void refresh();
      },
    },
  });
  const disable = useDisableSecondFactor({
    mutation: {
      onSuccess: () => {
        setDisabling(false);
        setCode("");
        void refresh();
        void message.success(t("secondFactor.disabled"));
      },
    },
  });

  const enabled = status.data?.enabled ?? false;
  // ДВ-4б: фактор обязателен по разделам доступа — отключить нельзя, а без него вход закрыт
  const required = status.data?.required ?? false;
  return (
    <Section title={t("secondFactor.title")} lead={t("secondFactor.lead")} testId="profile-2fa">
      {backup ? (
        <BackupCodes
          codes={backup}
          onSaved={() => {
            setBackup(null);
          }}
        />
      ) : setup ? (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <p style={{ margin: 0 }}>{t("secondFactor.scan")}</p>
          <QRCode
            type="svg"
            value={setup.otpauth_uri}
            size={168}
            bordered={false}
            aria-label={t("secondFactor.qrLabel")}
          />
          <p className="pf-hint" style={{ margin: 0 }}>
            {t("secondFactor.manual")}{" "}
            <Typography.Text code copyable className="pf-num">
              {setup.secret}
            </Typography.Text>
          </p>
          <Form
            layout="vertical"
            requiredMark={false}
            onFinish={() => {
              enable.mutate({ data: { code: code.trim() } });
            }}
          >
            <Form.Item label={t("secondFactor.code")} htmlFor={codeId} style={{ maxWidth: 240 }}>
              <Input
                id={codeId}
                value={code}
                onChange={(event) => {
                  setCode(event.target.value);
                }}
                autoComplete="one-time-code"
                inputMode="numeric"
                maxLength={6}
                className="pf-num"
              />
            </Form.Item>
            {enable.isError ? (
              <Alert
                type="error"
                showIcon
                role="alert"
                message={reasonText(t, enable.error)}
                style={{ marginBottom: 12 }}
              />
            ) : null}
            <Space wrap>
              <Button
                type="primary"
                htmlType="submit"
                loading={enable.isPending}
                disabled={code.trim().length < 6}
              >
                {t("secondFactor.confirm")}
              </Button>
              <Button
                onClick={() => {
                  setSetup(null);
                }}
              >
                {t("secondFactor.cancel")}
              </Button>
            </Space>
          </Form>
        </Space>
      ) : enabled ? (
        <Space direction="vertical" size={12}>
          <p style={{ margin: 0 }}>
            {t("secondFactor.on", {
              date: status.data?.enabled_at ? date(status.data.enabled_at) : "",
              left: status.data?.backup_codes_left ?? 0,
            })}
          </p>
          {required ? (
            <p className="pf-hint" style={{ margin: 0 }}>
              {t("secondFactor.requiredNote")}
            </p>
          ) : (
            <Button
              onClick={() => {
                setDisabling(true);
              }}
            >
              {t("secondFactor.disable")}
            </Button>
          )}
        </Space>
      ) : (
        <Space direction="vertical" size={12}>
          <p style={{ margin: 0 }}>
            {t(required ? "secondFactor.offRequired" : "secondFactor.off")}
          </p>
          {start.isError ? (
            <Alert type="error" showIcon role="alert" message={reasonText(t, start.error)} />
          ) : null}
          <Button
            type="primary"
            loading={start.isPending || status.isPending}
            onClick={() => {
              start.mutate();
            }}
          >
            {t("secondFactor.enable")}
          </Button>
        </Space>
      )}
      <Dialog
        open={disabling}
        title={t("secondFactor.disableTitle")}
        okLabel={t("secondFactor.disable")}
        danger
        loading={disable.isPending}
        okDisabled={code.trim().length < 6}
        onOk={() => {
          disable.mutate({ data: { code: code.trim() } });
        }}
        onCancel={() => {
          setDisabling(false);
          setCode("");
        }}
      >
        <Form layout="vertical" requiredMark={false}>
          <Form.Item label={t("secondFactor.codeOrBackup")} htmlFor={`${codeId}-off`}>
            <Input
              id={`${codeId}-off`}
              value={code}
              onChange={(event) => {
                setCode(event.target.value);
              }}
              autoComplete="one-time-code"
              maxLength={9}
              className="pf-num"
              autoFocus
            />
          </Form.Item>
        </Form>
        {disable.isError ? (
          <Alert type="error" showIcon role="alert" message={reasonText(t, disable.error)} />
        ) : null}
      </Dialog>
    </Section>
  );
}
