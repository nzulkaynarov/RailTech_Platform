import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Segmented } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { Zone, ZonePerson } from "../../../shared/api/generated/model";
import {
  getGetQueueCardsQueryKey,
  getGetResponsibilityZonesSummaryQueryKey,
  getListResponsibilityZonesQueryKey,
  useListResponsibilityZones,
} from "../../../shared/api/generated/platform-bff";
import type { DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { FilterBar } from "../../../shared/ui/FilterBar";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { ListTable } from "../company/common";
import { SettingsPage } from "../settings/SettingsPage";
import { zoneText } from "./model";
import { ZoneSheet, type ZoneTarget } from "./ZoneSheet";

type Filter = "active" | "all";

function PersonCell({ person }: { person: ZonePerson | undefined }) {
  const { t } = useTranslation("zones");
  if (!person) return <span className="pf-hint">{t("notAssigned")}</span>;
  return (
    <div>
      <b>{person.name}</b>
      <div className="pf-hint">{person.active ? (person.position ?? "") : t("personInactive")}</div>
    </div>
  );
}

/**
 * Настройки · Люди и доступ · Зоны ответственности (ЕВ-З, решение владельца 2026-11-23). Реестр «зона → ответственный →
 * замещающий → куратор» по образцу реестра прав подписи: основание, срок, журнал. «Что не так» приходит готовым из CRM и
 * считается по фактам при каждом чтении. Зоны пока только записаны: уведомления и согласования они не направляют.
 */
export function ZonesPage() {
  const { t, i18n } = useTranslation("zones");
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<Filter>("active");
  const [target, setTarget] = useState<ZoneTarget | null>(null);
  const list = useListResponsibilityZones();
  const canAssign = canEdit(me, "company.settings");
  const canManage = canEdit(me, "admin");
  const all = list.data?.items ?? [];
  const rows = filter === "active" ? all.filter((zone) => zone.active) : all;

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: getListResponsibilityZonesQueryKey() });
    // Сигнал «зона без ответственного» на Настройках и Главной обновляется сразу.
    void queryClient.invalidateQueries({ queryKey: getGetResponsibilityZonesSummaryQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getGetQueueCardsQueryKey() });
  };

  const add = canManage ? (
    <Button
      type="primary"
      onClick={() => {
        setTarget({ mode: "new" });
      }}
    >
      {t("add")}
    </Button>
  ) : undefined;

  const columns: DataColumn<Zone>[] = [
    {
      id: "zone",
      header: t("col.zone"),
      width: null,
      cell: (row) => (
        <div>
          <b>{zoneText(row.name, i18n.language)}</b>
          {!row.active ? <StatusTag tone="default">{t("off")}</StatusTag> : null}
          <div className="pf-hint">{zoneText(row.description, i18n.language)}</div>
        </div>
      ),
    },
    {
      id: "responsible",
      header: t("col.responsible"),
      width: null,
      cell: (row) => <PersonCell person={row.responsible} />,
    },
    {
      id: "deputy",
      header: t("col.deputy"),
      width: null,
      cell: (row) => <PersonCell person={row.deputy} />,
    },
    {
      id: "curator",
      header: t("col.curator"),
      width: null,
      cell: (row) => <PersonCell person={row.curator} />,
    },
    {
      id: "problems",
      header: t("col.problems"),
      width: null,
      cell: (row) =>
        row.problems.length === 0 ? (
          <span className="pf-hint">{row.active ? t("noProblems") : "—"}</span>
        ) : (
          <div>
            {row.problems.map((problem) =>
              problem.severity === "warning" ? (
                <StatusTag key={problem.code} tone="gold">
                  {t(`problem.${problem.code}`)}
                </StatusTag>
              ) : (
                <StatusTag key={problem.code} tone="red">
                  {t(`problem.${problem.code}`)}
                </StatusTag>
              ),
            )}
          </div>
        ),
    },
    {
      id: "actions",
      header: t("col.actions"),
      headerHidden: true,
      width: 120,
      cell: (row) => (
        <Button
          type="link"
          size="small"
          aria-label={t("openNamed", { name: zoneText(row.name, i18n.language) })}
          onClick={() => {
            setTarget({ mode: "edit", id: row.id });
          }}
        >
          {t("open")}
        </Button>
      ),
    },
  ];

  return (
    <SettingsPage sectionKey="zones" subtitle={t("subtitle")} extra={add} editable={canAssign}>
      <FilterBar>
        <Segmented<Filter>
          aria-label={t("filter.label")}
          value={filter}
          onChange={setFilter}
          options={[
            { value: "active", label: t("filter.active") },
            { value: "all", label: t("filter.all") },
          ]}
        />
      </FilterBar>
      {list.isError ? (
        <Alert type="error" showIcon role="alert" message={t("unavailable")} />
      ) : null}
      <ListTable<Zone>
        tableId="admin.zones"
        label={t("list.label")}
        data={rows}
        loading={list.isPending}
        rowKey={(row) => row.id}
        columns={columns}
        empty={{
          title: t("empty.title"),
          text: filter === "active" && all.length > 0 ? t("empty.activeText") : t("empty.text"),
          action: list.isPending ? undefined : add,
        }}
      />
      <p className="pf-hint">{t("note")}</p>
      {target ? (
        <ZoneSheet
          target={target}
          zones={all}
          canAssign={canAssign}
          canManage={canManage}
          onChanged={refresh}
          onClose={() => {
            setTarget(null);
          }}
        />
      ) : null}
    </SettingsPage>
  );
}
