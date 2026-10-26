import { Alert, Button, Input } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ErpCheck, ErpConnector } from "../../../shared/api/generated/model";
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

function PairForm({ erp, onDone }: { erp: ErpConnector; onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const [baseUrl, setBaseUrl] = useState(erp.configured ? erp.base_url : erp.suggested_base_url);
  const [code, setCode] = useState("");
  const pair = usePairErp({
    mutation: {
      onSuccess: () => {
        refresh();
      },
    },
  });
  const result = pair.data;
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
        onCancel={onDone}
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
      {result ? (
        <div className="pf-int-form">
          <Alert type="success" showIcon role="status" message={t("erp.pair.done")} />
          {result.check ? <CheckResult check={result.check} /> : null}
          {result.check_error ? (
            <Alert
              type="warning"
              showIcon
              role="status"
              message={reasonText(t, result.check_error) || t("errors.INTEGRATION_FAILED")}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function RotateForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const rotate = useRotateErpKeys({
    mutation: {
      onSuccess: () => {
        refresh();
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
        onCancel={onDone}
        onSubmit={(password) => {
          rotate.mutate({ data: { password } });
        }}
      />
      {rotate.data ? (
        <>
          <Alert type="success" showIcon role="status" message={t("erp.rotate.done")} />
          {rotate.data.check ? <CheckResult check={rotate.data.check} /> : null}
        </>
      ) : null}
    </div>
  );
}

function ErpBody({ erp, editable }: { erp: ErpConnector; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  const refresh = useRefreshIntegrations();
  const [form, setForm] = useState<"pair" | "rotate" | null>(null);
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
              setForm(open ? "pair" : null);
            }}
          >
            <PairForm
              erp={erp}
              onDone={() => {
                setForm(null);
              }}
            />
          </ActionToggle>
          {erp.configured ? (
            <ActionToggle
              label={t("erp.rotate.button")}
              open={form === "rotate"}
              onToggle={(open) => {
                setForm(open ? "rotate" : null);
              }}
            >
              <RotateForm
                onDone={() => {
                  setForm(null);
                }}
              />
            </ActionToggle>
          ) : null}
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
