import { Alert, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ServiceAction, ServiceGroup } from "../../../shared/api/generated/model";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { useRecheck, useSinceText } from "./healthHooks";
import {
  KeyForm,
  OwnerLine,
  ProviderSwitch,
  StateTag,
  TechnicalDetails,
  WriteBox,
} from "./HealthParts";

const PATH = "/admin/integrations";
type Panel = "key" | "write" | "switch" | null;

/** Какое действие раскрывает форму под строкой, а какое — открывает карточку или проверяет сразу. */
const PANEL_OF: Partial<Record<ServiceAction, Exclude<Panel, null>>> = {
  enter_key: "key",
  write_owner: "write",
  write_hosting: "write",
  disable_provider: "switch",
};

/**
 * Строка «Требует внимания»: одна причина — одна строка (W15-H3). Состояние словом, что случилось и что перестало
 * работать, «с {время}», «Кто исправляет», одно главное действие по смыслу и запасные. Сырой текст сервиса — только под
 * «Технические подробности». Решения принимает CRM; здесь только показ и действия.
 */
export function AttentionGroupRow({
  group,
  editable,
  severity,
}: {
  group: ServiceGroup;
  editable: boolean;
  severity: string;
}) {
  const { t } = useTranslation("integrations");
  const [panel, setPanel] = useState<Panel>(null);
  const recheck = useRecheck(group);
  const sinceText = useSinceText(group.since);
  const expected = group.state === "expected";
  const affectedKey =
    group.state === "broken" || group.state === "degraded" ? group.state : "other";
  const headline = group.headline;

  const needsAdmin = (action: ServiceAction) =>
    action !== "open_settings" && action !== "write_owner" && action !== "write_hosting";
  const actions = [group.action, ...group.more_actions]
    .filter(
      (action, index, all): action is ServiceAction =>
        action !== null && all.indexOf(action) === index,
    )
    .filter((action) => editable || !needsAdmin(action))
    .filter(
      (action) =>
        !(action === "write_owner" || action === "write_hosting") || group.message !== null,
    );

  const renderAction = (action: ServiceAction, primary: boolean) => {
    const label = t(`health.action.${action}`);
    const aria = t("health.actionAria", { action: label, subject: headline });
    const type = primary ? "primary" : "default";
    const target = PANEL_OF[action];
    if (action === "recheck") {
      return (
        <Button
          key={action}
          type={type}
          loading={recheck.running}
          aria-label={aria}
          onClick={() => void recheck.run()}
        >
          {label}
        </Button>
      );
    }
    if (target !== undefined) {
      return (
        <Button
          key={action}
          type={type}
          danger={action === "disable_provider"}
          aria-label={aria}
          aria-expanded={panel === target}
          onClick={() => {
            setPanel(panel === target ? null : target);
          }}
        >
          {label}
        </Button>
      );
    }
    return (
      <LinkButton
        key={action}
        type={type}
        aria-label={aria}
        to={`${PATH}?card=${group.fix_card ?? "services"}&panel=open`}
      >
        {label}
      </LinkButton>
    );
  };

  const who = group.action === "write_hosting" || group.owner === "hosting" ? "hosting" : "owner";
  return (
    <li
      data-severity={severity}
      data-state={group.state}
      data-group={group.id}
      className="pf-health"
    >
      <div className="pf-health-head">
        <StateTag state={group.state} />
        <span className="pf-health-headline">
          {headline}
          {group.affected.length > 0
            ? ` — ${t(`health.affected.${affectedKey}`, { list: group.affected.join(", ") })}`
            : ""}
        </span>
      </div>
      <p className="pf-health-meta">
        <span>{sinceText}</span>
        <OwnerLine owner={group.owner} action={group.action} />
        {group.flaps_24h > 0 && group.state !== "ok" ? (
          <span>{t("health.flaps", { count: group.flaps_24h })}</span>
        ) : null}
      </p>
      {expected ? <p className="pf-int-sub">{t("health.expectedNote")}</p> : null}
      {group.detail && !expected ? <p className="pf-int-sub">{group.detail}</p> : null}
      {actions.length > 0 ? (
        <div className="pf-int-row">
          {actions.map((action, index) => renderAction(action, index === 0))}
        </div>
      ) : null}
      {recheck.outcome ? (
        <Alert type={recheck.outcome.type} showIcon role="status" message={recheck.outcome.text} />
      ) : null}
      {panel === "key" ? (
        <KeyForm
          group={group}
          onDone={() => {
            setPanel(null);
          }}
        />
      ) : null}
      {panel === "write" && group.message !== null ? (
        <WriteBox who={who} text={group.message} headline={headline} />
      ) : null}
      {panel === "switch" ? (
        <ProviderSwitch
          group={group}
          onDone={() => {
            setPanel(null);
          }}
        />
      ) : null}
      <TechnicalDetails
        lines={group.technical}
        context={{
          services: group.titles.join(", "),
          state: t(`health.state.${group.state}`),
          since: sinceText,
        }}
      />
    </li>
  );
}
