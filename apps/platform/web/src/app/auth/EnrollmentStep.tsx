import { Alert, Button, Form, Input, QRCode, Space, Spin, Typography } from "antd";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Session } from "../../shared/api/generated/model";
import { useLoginEnroll, useLoginEnrollSetup } from "../../shared/api/generated/platform-bff";
import { ApiError } from "../../shared/api/errors";
import { BackupCodes } from "../../features/profile/BackupCodes";
import { AuthLayout } from "./AuthLayout";
import { authErrorText } from "./errors";

/**
 * Обязательная настройка второго фактора сразу после пароля (ДВ-4б, реестр рисков Д1): доступ сотрудника включает
 * оплаты, одобрения или настройки, вход без кода закрыт. Экран ведёт до конца: QR-код, код из приложения, резервные
 * коды — и только потом сессия. Время вышло — назад к паролю.
 */
export function EnrollmentStep({
  challenge,
  onSignedIn,
  onRestart,
}: {
  challenge: string;
  onSignedIn: (session: Session) => void;
  onRestart: () => void;
}) {
  const { t } = useTranslation("shell");
  const { t: tProfile } = useTranslation("profile");
  const codeId = useId();
  const [code, setCode] = useState("");
  const [signed, setSigned] = useState<{ session: Session; codes: string[] } | null>(null);
  const setup = useLoginEnrollSetup({ mutation: { gcTime: 0 } });
  const enroll = useLoginEnroll({
    mutation: {
      gcTime: 0,
      onSuccess: ({ backup_codes: codes, ...session }) => {
        setSigned({ session, codes });
      },
      onError: (error) => {
        if (error instanceof ApiError && error.code === "SECOND_FACTOR_EXPIRED") onRestart();
      },
    },
  });
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    setup.mutate({ data: { challenge } });
  }, [challenge, setup]);

  if (signed) {
    return (
      <AuthLayout title={t("login.enroll.doneTitle")}>
        <BackupCodes
          codes={signed.codes}
          onSaved={() => {
            onSignedIn(signed.session);
          }}
        />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={t("login.enroll.title")} lead={t("login.enroll.lead")}>
      {setup.isPending || setup.isIdle ? (
        <div role="status" aria-label={t("loading")} style={{ textAlign: "center" }}>
          <Spin />
        </div>
      ) : setup.isError ? (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="error"
            showIcon
            role="alert"
            message={authErrorText(t, "login", setup.error)}
          />
          <Button block onClick={onRestart}>
            {t("login.secondFactor.back")}
          </Button>
        </Space>
      ) : (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <p style={{ margin: 0 }}>{tProfile("secondFactor.scan")}</p>
          <QRCode
            type="svg"
            value={setup.data.otpauth_uri}
            size={168}
            bordered={false}
            aria-label={tProfile("secondFactor.qrLabel")}
          />
          <p className="pf-hint" style={{ margin: 0 }}>
            {tProfile("secondFactor.manual")}{" "}
            <Typography.Text code copyable className="pf-num">
              {setup.data.secret}
            </Typography.Text>
          </p>
          {enroll.isError ? (
            <Alert
              type="error"
              showIcon
              role="alert"
              message={authErrorText(t, "login", enroll.error)}
            />
          ) : null}
          <Form
            layout="vertical"
            requiredMark={false}
            onFinish={() => {
              enroll.mutate({ data: { challenge, code: code.trim() } });
            }}
          >
            <Form.Item label={tProfile("secondFactor.code")} htmlFor={codeId}>
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
                autoFocus
              />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={enroll.isPending}
              disabled={code.trim().length < 6}
            >
              {tProfile("secondFactor.confirm")}
            </Button>
            <Button type="link" style={{ padding: 0, marginTop: 12 }} onClick={onRestart}>
              {t("login.secondFactor.back")}
            </Button>
          </Form>
        </Space>
      )}
    </AuthLayout>
  );
}
