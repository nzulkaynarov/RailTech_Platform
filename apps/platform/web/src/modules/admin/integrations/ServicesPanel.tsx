import { Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ExternalService } from "../../../shared/api/generated/model";
import {
  useCheckExternalService,
  useListExternalServices,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { OwnerLine, StateTag } from "./HealthParts";
import { ErrorNote, PanelState, PanelTitle } from "./parts";
import { useRefreshIntegrations } from "./refresh";
import { SwitchForm } from "./SwitchForm";

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
          <StateTag state={paused ? "disabled" : service.state} />
          {paused ? <span className="pf-hint">{t("services.pausedTag")}</span> : null}
        </span>
      </div>
      <p className="pf-int-sub">{service.purpose}</p>
      <p className="pf-int-sub">
        {service.state === "not_checked" ? t("health.notChecked") : service.summary}
      </p>
      {service.state === "broken" ||
      service.state === "unstable" ||
      service.state === "degraded" ? (
        <p className="pf-health-meta">
          {service.since ? (
            <span>{t("health.since", { date: date(service.since, "datetime") })}</span>
          ) : null}
          <OwnerLine owner={service.owner} action={service.action} />
          {service.flaps_24h > 0 ? (
            <span>{t("health.flaps", { count: service.flaps_24h })}</span>
          ) : null}
        </p>
      ) : null}
      {service.state === "expected" ? (
        <p className="pf-int-sub">{t("health.expectedNote")}</p>
      ) : null}
      {service.state !== "ok" && service.state !== "expected" && service.hint ? (
        <p className="pf-int-sub">{t("services.hint", { hint: service.hint })}</p>
      ) : null}
      {service.state === "ok" && service.last_recovered_at ? (
        <p className="pf-int-sub">
          {t("health.recoveredAt", { date: date(service.last_recovered_at, "datetime") })}
        </p>
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
