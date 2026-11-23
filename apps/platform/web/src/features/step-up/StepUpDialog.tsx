import { Alert, Button, Form, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError } from "../../shared/api/errors";
import { useStepUpSecondFactor } from "../../shared/api/generated/platform-bff";
import { rememberStepUp } from "../../shared/api/stepUp";
import { Dialog } from "../../shared/ui/Dialog";

export interface PendingStepUp {
  retry: () => void;
  notEnrolled: boolean;
}

/** Окно «свежий код» (ДВ-4б): код из приложения → токен на 5 минут → отказавшее действие повторяется. */
export function StepUpDialog({
  pending,
  onClose,
}: {
  pending: PendingStepUp;
  onClose: () => void;
}) {
  const { t } = useTranslation("profile");
  const codeId = useId();
  const [code, setCode] = useState("");
  const verify = useStepUpSecondFactor({
    mutation: {
      onSuccess: (issued) => {
        rememberStepUp(issued.token);
        onClose();
        pending.retry();
      },
    },
  });

  if (pending.notEnrolled) {
    return (
      <Dialog
        title={t("stepUp.notEnrolledTitle")}
        onCancel={onClose}
        footer={
          <>
            <Button onClick={onClose}>{t("stepUp.close")}</Button>
            <Link to="/me" onClick={onClose}>
              <Button type="primary">{t("stepUp.toProfile")}</Button>
            </Link>
          </>
        }
      >
        <p style={{ margin: 0 }}>{t("stepUp.notEnrolled")}</p>
      </Dialog>
    );
  }

  const submit = () => {
    if (code.trim().length >= 6) verify.mutate({ data: { code: code.trim() } });
  };
  return (
    <Dialog
      title={t("stepUp.title")}
      okLabel={t("stepUp.confirm")}
      loading={verify.isPending}
      okDisabled={code.trim().length < 6}
      onOk={submit}
      onCancel={onClose}
    >
      <p style={{ marginTop: 0 }}>{t("stepUp.lead")}</p>
      <Form layout="vertical" requiredMark={false} onFinish={submit}>
        <Form.Item label={t("stepUp.code")} htmlFor={codeId}>
          <Input
            id={codeId}
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
      {verify.isError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          description={
            verify.error instanceof ApiError &&
            verify.error.details["reason"] === "second_factor_code_invalid"
              ? t("stepUp.hint")
              : undefined
          }
          message={t(
            verify.error instanceof ApiError &&
              verify.error.details["reason"] === "second_factor_code_invalid"
              ? "stepUp.wrong"
              : verify.error instanceof ApiError && verify.error.code === "ACCOUNT_LOCKED"
                ? "stepUp.locked"
                : "stepUp.default",
          )}
        />
      ) : null}
    </Dialog>
  );
}
