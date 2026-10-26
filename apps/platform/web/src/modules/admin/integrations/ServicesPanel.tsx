import { Button, Input } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ExternalService } from "../../../shared/api/generated/model";
import {
  useCheckExternalService,
  useDisableExternalService,
  useEnableExternalService,
  useListExternalServices,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { ActionForm, ErrorNote, Field, LevelTag, PanelState, PanelTitle } from "./parts";
import { useRefreshIntegrations } from "./refresh";

function SwitchForm({ service, onDone }: { service: ExternalService; onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const [reason, setReason] = useState("");
  const disabled = service.switch?.disabled ?? false;
  const onSuccess = () => {
    refresh();
    onDone();
  };
  const disable = useDisableExternalService({ mutation: { onSuccess } });
  const enable = useEnableExternalService({ mutation: { onSuccess } });
  const active = disabled ? enable : disable;
  const effect = service.switch?.effect;
  return (
    <ActionForm
      id={`svc-${service.key}`}
      title={t(disabled ? "services.enable.title" : "services.disable.title", {
        title: service.title,
      })}
      submitLabel={t(disabled ? "services.enable.submit" : "services.disable.submit")}
      danger={!disabled}
      pending={active.isPending}
      error={active.error}
      consequence={
        disabled
          ? [t("services.enable.step1"), t("services.enable.step2")]
          : [
              effect ?? t("services.disable.step1"),
              t("services.disable.step2"),
              t("services.disable.step3"),
            ]
      }
      onCancel={onDone}
      onSubmit={(password) => {
        if (disabled) enable.mutate({ key: service.key, data: { password } });
        else
          disable.mutate({
            key: service.key,
            data: { password, ...(reason.trim() ? { reason: reason.trim() } : {}) },
          });
      }}
    >
      {disabled ? null : (
        <Field id={`svc-${service.key}-reason`} label={t("services.disable.reason")}>
          <Input
            id={`svc-${service.key}-reason`}
            value={reason}
            maxLength={200}
            autoComplete="off"
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
        </Field>
      )}
    </ActionForm>
  );
}

function ServiceRow({ service, editable }: { service: ExternalService; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const { date, percent } = useFormat();
  const refresh = useRefreshIntegrations();
  const [switching, setSwitching] = useState(false);
  const check = useCheckExternalService({
    mutation: {
      onSuccess: () => {
        refresh();
      },
    },
  });
  const paused = service.switch?.disabled ?? false;
  const canSwitch = editable && service.switch?.available === true;
  return (
    <li>
      <div className="pf-int-item-head">
        <span className="pf-int-item-title">{service.title}</span>
        <span className="pf-int-row">
          {paused ? <LevelTag level="off" /> : <LevelTag level={service.status} />}
          {paused ? <span className="pf-hint">{t("services.pausedTag")}</span> : null}
        </span>
      </div>
      <p className="pf-int-sub">{service.purpose}</p>
      <p className="pf-int-sub">{service.summary}</p>
      {service.status !== "ok" && service.hint ? (
        <p className="pf-int-sub">{t("services.hint", { hint: service.hint })}</p>
      ) : null}
      <p className="pf-int-sub">
        {service.checked_at
          ? t("services.checkedAt", { date: date(service.checked_at, "datetime") })
          : t("services.neverChecked")}
        {service.uptime_24h !== null
          ? ` · ${t("services.uptime", { value: percent(service.uptime_24h * 100) })}`
          : ""}
      </p>
      {paused && service.switch?.reason ? (
        <p className="pf-int-sub">
          {t("services.pausedReason", { reason: service.switch.reason })}
        </p>
      ) : null}
      {editable ? (
        <div className="pf-int-row">
          <Button
            size="small"
            loading={check.isPending}
            aria-label={t("services.checkAria", { title: service.title })}
            onClick={() => {
              check.mutate({ key: service.key });
            }}
          >
            {t("common.check")}
          </Button>
          {canSwitch ? (
            <Button
              size="small"
              danger={!paused}
              aria-expanded={switching}
              aria-label={t(paused ? "services.enable.aria" : "services.disable.aria", {
                title: service.title,
              })}
              onClick={() => {
                setSwitching(!switching);
              }}
            >
              {t(paused ? "services.enable.button" : "services.disable.button")}
            </Button>
          ) : null}
        </div>
      ) : null}
      <ErrorNote error={check.error} />
      {switching ? (
        <SwitchForm
          service={service}
          onDone={() => {
            setSwitching(false);
          }}
        />
      ) : null}
    </li>
  );
}

/** Карточка «Внешние сервисы»: реестр CRM (ADR-0024 CRM) — статус, «Проверить», включить и выключить с «Что произойдёт». */
export function ServicesPanel({ editable }: { editable: boolean }) {
  const { t } = useTranslation("integrations");
  const query = useListExternalServices();
  return (
    <div className="pf-panel-stack">
      <PanelTitle>{t("cards.services.title")}</PanelTitle>
      <PanelState query={query}>
        {(list) => (
          <>
            <p className="pf-int-sub">
              {t("services.summary", {
                ok: list.summary.ok,
                warn: list.summary.warn,
                fail: list.summary.fail,
                unknown: list.summary.unknown,
                off: list.summary.off,
              })}
            </p>
            {!editable ? (
              <p className="pf-hint" style={{ margin: 0 }}>
                {t("common.readOnly")}
              </p>
            ) : null}
            <ul className="pf-int-list" aria-label={t("cards.services.title")}>
              {list.items.map((service) => (
                <ServiceRow key={service.key} service={service} editable={editable} />
              ))}
            </ul>
          </>
        )}
      </PanelState>
    </div>
  );
}
