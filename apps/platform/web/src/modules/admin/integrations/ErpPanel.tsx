import { Alert, Button, Input } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ErpCheck, ErpConnector, ErpPairing } from "../../../shared/api/generated/model";
import {
  useCheckErpConnector,
  useGetErpConnector,
  usePairErp,
  useRotateErpKeys,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { reasonText } from "./errors";
import {
  ActionForm,
  ActionToggle,
  ErrorNote,
  Field,
  Masked,
  PanelState,
  PanelTitle,
} from "./parts";
import { useRefreshIntegrations } from "./refresh";

/** Итог «Проверить связь» словами: ERP ответила, ответила с замечаниями или просит подождать. */
function CheckResult({ check }: { check: ErpCheck }) {
  const { t } = useTranslation("integrations");
  if (check.status === "rate_limited") {
    return (
      <Alert
        type="warning"
        showIcon
        role="status"
        message={t("erp.check.rateLimited", { seconds: check.retry_after_s ?? 0 })}
      />
    );
  }
  const details = [
    check.version ? t("erp.check.version", { version: check.version }) : null,
    check.latency_ms !== null ? t("erp.check.latency", { ms: check.latency_ms }) : null,
    check.migrations_applied === false ? t("erp.check.migrations") : null,
    check.queue_alive === false ? t("erp.check.queue") : null,
  ].filter(Boolean);
  return (
    <Alert
      type={check.status === "ok" ? "success" : "warning"}
      showIcon
      role="status"
      message={t(check.status === "ok" ? "erp.check.ok" : "erp.check.degraded")}
      description={details.join(" · ") || undefined}
    />
  );
}

type ErpResult = { kind: "pair" | "rotate"; data: ErpPairing };

/** Итог сопряжения или ротации: остаётся на панели после закрытия формы (код и пароль из формы уходят). */
function ResultNote({ result }: { result: ErpResult }) {
  const { t } = useTranslation("integrations");
  const { data } = result;
  return (
    <div className="pf-int-form">
      <Alert
        type="success"
        showIcon
        role="status"
        message={t(result.kind === "pair" ? "erp.pair.done" : "erp.rotate.done")}
      />
      {data.check ? <CheckResult check={data.check} /> : null}
      {data.check_error ? (
        <Alert
          type="warning"
          showIcon
          role="status"
          message={reasonText(t, data.check_error) || t("errors.INTEGRATION_FAILED")}
        />
      ) : null}
    </div>
  );
}

function PairForm({
  erp,
  onSaved,
  onCancel,
}: {
  erp: ErpConnector;
  onSaved: (result: ErpResult) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const [baseUrl, setBaseUrl] = useState(erp.configured ? erp.base_url : erp.suggested_base_url);
  const [code, setCode] = useState("");
  const pair = usePairErp({
    mutation: {
      onSuccess: (data) => {
        refresh();
        // Форма закрывается и размонтируется: код сопряжения и пароль не остаются в состоянии.
        setCode("");
        onSaved({ kind: "pair", data });
      },
    },
  });
  return (
    <div className="pf-int-form">
      <ActionForm
        id="erp-pair"
        title={t("erp.pair.title")}
        submitLabel={t("erp.pair.submit")}
        pending={pair.isPending}
        error={pair.error}
        invalid={baseUrl.trim() === ""}
        consequence={[t("erp.pair.step1"), t("erp.pair.step2"), t("erp.pair.step3")]}
        onCancel={onCancel}
        onSubmit={(password) => {
          pair.mutate({
            data: {
              base_url: baseUrl.trim(),
              ...(code.trim() ? { code: code.trim() } : {}),
              password,
            },
          });
        }}
      >
        <Field id="erp-pair-url" label={t("erp.pair.url")} hint={t("erp.pair.urlHint")}>
          <Input
            id="erp-pair-url"
            value={baseUrl}
            inputMode="url"
            autoComplete="off"
            onChange={(event) => {
              setBaseUrl(event.target.value);
            }}
          />
        </Field>
        <Field id="erp-pair-code" label={t("erp.pair.code")} hint={t("erp.pair.codeHint")}>
          <Input
            id="erp-pair-code"
            type="password"
            autoComplete="off"
            value={code}
            onChange={(event) => {
              setCode(event.target.value);
            }}
          />
        </Field>
      </ActionForm>
    </div>
  );
}

function RotateForm({
  onSaved,
  onCancel,
}: {
  onSaved: (result: ErpResult) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const rotate = useRotateErpKeys({
    mutation: {
      onSuccess: (data) => {
        refresh();
        onSaved({ kind: "rotate", data });
      },
    },
  });
  return (
    <div className="pf-int-form">
      <ActionForm
        id="erp-rotate"
        title={t("erp.rotate.title")}
        submitLabel={t("erp.rotate.submit")}
        pending={rotate.isPending}
        error={rotate.error}
        consequence={[t("erp.rotate.step1"), t("erp.rotate.step2"), t("erp.rotate.step3")]}
        onCancel={onCancel}
        onSubmit={(password) => {
          rotate.mutate({ data: { password } });
        }}
      />
    </div>
  );
}

function ErpBody({ erp, editable }: { erp: ErpConnector; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  const refresh = useRefreshIntegrations();
  const [form, setForm] = useState<"pair" | "rotate" | null>(null);
  const [saved, setSaved] = useState<ErpResult | null>(null);
  const finish = (result: ErpResult) => {
    setSaved(result);
    setForm(null);
  };
  const check = useCheckErpConnector({
    mutation: {
      onSuccess: () => {
        refresh();
      },
    },
  });
  return (
    <div className="pf-panel-stack">
      <DefinitionList
        items={[
          {
            label: t("erp.state"),
            value: erp.configured
              ? erp.paired
                ? t("erp.stateValue.paired")
                : t("erp.stateValue.configured")
              : t("erp.stateValue.none"),
          },
          { label: t("erp.url"), value: erp.configured ? erp.base_url : null },
          {
            label: t("erp.token"),
            value: <Masked configured={erp.token_configured} last4={erp.token_last4} />,
          },
          {
            label: t("erp.webhook"),
            value: (
              <Masked configured={erp.webhook_secret_configured} last4={erp.webhook_secret_last4} />
            ),
          },
          {
            label: t("erp.updated"),
            value: erp.token_updated_at ? date(erp.token_updated_at, "datetime") : null,
          },
          ...(erp.rotation_pending
            ? [
                {
                  label: t("erp.rotationUntil"),
                  value: erp.previous_secret_until
                    ? date(erp.previous_secret_until, "datetime")
                    : t("erp.rotationNow"),
                },
              ]
            : []),
        ]}
      />
      {!erp.secrets_enabled ? (
        <Alert type="warning" showIcon message={t("common.secretsOff")} />
      ) : null}
      {!editable ? (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("common.readOnly")}
        </p>
      ) : (
        <>
          {erp.configured ? (
            <div className="pf-int-form">
              <div className="pf-int-row">
                <Button
                  loading={check.isPending}
                  onClick={() => {
                    check.mutate();
                  }}
                >
                  {t("erp.check.button")}
                </Button>
              </div>
              {check.data ? <CheckResult check={check.data} /> : null}
              <ErrorNote error={check.error} />
            </div>
          ) : null}
          <ActionToggle
            label={erp.configured ? t("erp.pair.reconnect") : t("erp.pair.button")}
            open={form === "pair"}
            onToggle={(open) => {
              setSaved(null);
              setForm(open ? "pair" : null);
            }}
          >
            <PairForm
              erp={erp}
              onSaved={finish}
              onCancel={() => {
                setForm(null);
              }}
            />
          </ActionToggle>
          {erp.configured ? (
            <ActionToggle
              label={t("erp.rotate.button")}
              open={form === "rotate"}
              onToggle={(open) => {
                setSaved(null);
                setForm(open ? "rotate" : null);
              }}
            >
              <RotateForm
                onSaved={finish}
                onCancel={() => {
                  setForm(null);
                }}
              />
            </ActionToggle>
          ) : null}
          {saved ? <ResultNote result={saved} /> : null}
        </>
      )}
    </div>
  );
}

/** Карточка «ERP»: состояние сопряжения, «Проверить связь», «Подключить ERP», «Ротация ключей» (SPEC-v3 §7.6). */
export function ErpPanel({ editable }: { editable: boolean }) {
  const { t } = useTranslation("integrations");
  const query = useGetErpConnector();
  return (
    <div className="pf-panel-stack">
      <PanelTitle>{t("cards.erp.title")}</PanelTitle>
      <PanelState query={query}>{(erp) => <ErpBody erp={erp} editable={editable} />}</PanelState>
    </div>
  );
}
