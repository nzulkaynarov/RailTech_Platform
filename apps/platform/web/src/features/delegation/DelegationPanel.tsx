import { Alert, App, Badge, Button, Dropdown, Input, Skeleton, Switch } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { employeeErrorText } from "../../entities/employee/errors";
import { ApiError } from "../../shared/api/errors";
import type { DelegationLabel, Employee } from "../../shared/api/generated/model";
import {
  useGetDelegationCatalog,
  useGetEmployeeDelegation,
} from "../../shared/api/generated/platform-bff";
import { hasActiveLeads } from "../assign-role/leads";
import { TransferLeads } from "../assign-role/TransferLeads";
import { useEmployeeUpdate } from "../assign-role/useEmployeeMutations";
import { isStepUpError, useStepUp } from "../step-up/useStepUp";
import { useSaveDelegation } from "./useDelegation";

import "./delegation.css";

export interface DelegationPanelProps {
  employee: Employee;
  /** `Me.id` работающего администратора */
  selfId: string;
  /** Раздел `admin` на запись */
  canEdit: boolean;
}

function labelOf(label: DelegationLabel, language: string): string {
  const lng = language.startsWith("uz") ? "uz" : language.startsWith("en") ? "en" : "ru";
  return label[lng];
}

function sameSet(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((code) => b.includes(code));
}

/**
 * «Что делегировано» (СОТР-2): одно место, где человеку выдают права. Список действий по областям, у каждого
 * выключатель; «Предложить набор по должности» подставляет заготовку (роль компании); «Сохранить» появляется,
 * только когда что-то изменили. Должность — подпись, на права не влияет.
 */
export function DelegationPanel({ employee, selfId, canEdit }: DelegationPanelProps) {
  const { t, i18n } = useTranslation("modules");
  const { message } = App.useApp();
  const positionId = useId();
  const catalog = useGetDelegationCatalog();
  const mine = useGetEmployeeDelegation(employee.id);
  const [draft, setDraft] = useState<string[] | null>(null);
  const [presetId, setPresetId] = useState<string | null>(null);
  const [draftPosition, setDraftPosition] = useState<string | null>(null);
  const [transferTo, setTransferTo] = useState<string | null>(null);
  const stepUp = useStepUp();
  const editable = canEdit && employee.status !== "disabled";

  const reset = () => {
    setDraft(null);
    setPresetId(null);
    setDraftPosition(null);
    setTransferTo(null);
  };
  const saveDelegation = useSaveDelegation(employee.id, selfId, () => {
    reset();
    void message.success(t("admin.org.delegation.saved"));
  });
  const savePosition = useEmployeeUpdate(selfId, () => {
    reset();
    void message.success(t("admin.org.delegation.saved"));
  });

  const current = mine.data?.codes ?? [];
  const selected = draft ?? current;
  const changed = [
    ...selected.filter((code) => !current.includes(code)),
    ...current.filter((code) => !selected.includes(code)),
  ];
  const position = draftPosition ?? employee.position ?? "";
  const positionChanged = position.trim() !== (employee.position ?? "");
  const codesChanged = draft !== null && !sameSet(selected, current);
  const dirty = codesChanged || positionChanged;
  const blocker = codesChanged && selected.length === 0 ? t("admin.org.delegation.noneLeft") : null;
  const failure: unknown = saveDelegation.error ?? savePosition.error;
  const leads = saveDelegation.isError && hasActiveLeads(saveDelegation.error);

  const save = () => {
    const savePositionOnly = () => {
      savePosition.mutate({ id: employee.id, data: { position: position.trim() } });
    };
    if (!codesChanged) {
      savePositionOnly();
      return;
    }
    saveDelegation.mutate(
      {
        id: employee.id,
        data: {
          codes: selected,
          ...(presetId ? { preset_id: presetId } : {}),
          ...(leads && transferTo ? { transfer_to_user_id: transferTo } : {}),
        },
      },
      {
        onSuccess: () => {
          if (positionChanged) savePositionOnly();
        },
        onError: (error) => stepUp.ask(error, save),
      },
    );
  };

  if (catalog.isPending || mine.isPending) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (catalog.isError || mine.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("admin.org.delegation.loadError")}
        action={
          <Button
            size="small"
            onClick={() => {
              void catalog.refetch();
              void mine.refetch();
            }}
          >
            {t("admin.org.delegation.retry")}
          </Button>
        }
      />
    );
  }

  const { areas, actions, presets } = catalog.data;
  const suggested = mine.data.suggested_preset_id ?? null;
  const ordered = [...presets].sort(
    (a, b) => Number(b.id === suggested) - Number(a.id === suggested),
  );
  const toggle = (code: string, on: boolean) => {
    setDraft(on ? [...selected, code] : selected.filter((c) => c !== code));
  };
  const errorText =
    failure instanceof ApiError &&
    failure.code === "FORBIDDEN" &&
    failure.details["reason"] === "delegation_exceeds_own"
      ? t("admin.org.delegation.exceeds")
      : employeeErrorText(t, failure);

  return (
    <div className="pf-deleg">
      <div className="pf-deleg-head">
        <h3 className="pf-deleg-title">
          {t("admin.org.delegation.title")}
          <span className="pf-deleg-count">
            {t("admin.org.delegation.count", { count: selected.length })}
          </span>
        </h3>
        {editable ? (
          <Dropdown
            trigger={["click"]}
            menu={{
              items:
                ordered.length > 0
                  ? ordered.map((preset) => ({
                      key: preset.id,
                      label: `${preset.name} · ${t("admin.org.delegation.presetCount", { count: preset.codes.length })}`,
                    }))
                  : [
                      {
                        key: "none",
                        label: t("admin.org.delegation.presetsEmpty"),
                        disabled: true,
                      },
                    ],
              onClick: ({ key }) => {
                const preset = presets.find((p) => p.id === key);
                if (!preset) return;
                setDraft(preset.codes);
                setPresetId(preset.id);
                void message.info(t("admin.org.delegation.presetApplied", { name: preset.name }));
              },
            }}
          >
            <Button>{t("admin.org.delegation.suggest")}</Button>
          </Dropdown>
        ) : (
          <span className="pf-hint">{t("admin.org.delegation.readOnly")}</span>
        )}
      </div>
      <div className="pf-deleg-areas">
        {areas.map((area) => {
          const rows = actions.filter((action) => action.area === area.code);
          const on = rows.filter((action) => selected.includes(action.code)).length;
          return (
            <section
              key={area.code}
              className="pf-deleg-area"
              aria-label={labelOf(area.label, i18n.language)}
            >
              <h4 className="pf-deleg-area-title">
                <span>{labelOf(area.label, i18n.language)}</span>
                <span>
                  {on} / {rows.length}
                </span>
              </h4>
              {rows.map((action) => {
                const label = labelOf(action.label, i18n.language);
                const isChanged = changed.includes(action.code);
                return (
                  <div
                    key={action.code}
                    className={`pf-deleg-row${isChanged ? " pf-deleg-row--changed" : ""}`}
                  >
                    <span className="pf-deleg-row-label">{label}</span>
                    <span>
                      {isChanged ? (
                        <span className="pf-deleg-badge">
                          {t("admin.org.delegation.changedBadge")}
                        </span>
                      ) : null}
                      <Switch
                        size="small"
                        aria-label={label}
                        checked={selected.includes(action.code)}
                        disabled={!editable || saveDelegation.isPending}
                        onChange={(checked) => {
                          toggle(action.code, checked);
                        }}
                      />
                    </span>
                  </div>
                );
              })}
            </section>
          );
        })}
      </div>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("admin.org.delegation.also")}:{" "}
        <Link to="/admin/signing">{t("admin.org.delegation.alsoSigning")}</Link>
        {" · "}
        <Link to="/admin/zones">{t("admin.org.delegation.alsoZones")}</Link>
      </p>
      {editable ? (
        <div>
          <label htmlFor={positionId} style={{ display: "block", marginBottom: 4 }}>
            {t("admin.org.delegation.position")}
          </label>
          <Input
            id={positionId}
            value={position}
            maxLength={120}
            autoComplete="off"
            onChange={(event) => {
              setDraftPosition(event.target.value);
            }}
          />
          <p className="pf-hint" style={{ margin: "4px 0 0" }}>
            {t("admin.org.delegation.positionHint")}
          </p>
        </div>
      ) : null}
      {blocker ? <Alert type="warning" showIcon message={blocker} /> : null}
      {(saveDelegation.isError || savePosition.isError) && !isStepUpError(failure) ? (
        <Alert type="error" showIcon role="alert" message={errorText} />
      ) : null}
      {leads ? (
        <TransferLeads employee={employee} value={transferTo} onChange={setTransferTo} />
      ) : null}
      {editable && dirty ? (
        <div className="pf-deleg-bar" role="region" aria-label={t("admin.org.delegation.save")}>
          <Badge
            status="processing"
            text={t("admin.org.delegation.dirty", {
              count: changed.length + (positionChanged ? 1 : 0),
            })}
          />
          <span style={{ display: "flex", gap: 8 }}>
            <Button onClick={reset} disabled={saveDelegation.isPending || savePosition.isPending}>
              {t("admin.org.delegation.cancel")}
            </Button>
            <Button
              type="primary"
              loading={saveDelegation.isPending || savePosition.isPending}
              disabled={blocker !== null || (leads && !transferTo)}
              onClick={save}
            >
              {t("admin.org.delegation.save")}
            </Button>
          </span>
        </div>
      ) : null}
      {stepUp.dialog}
    </div>
  );
}
