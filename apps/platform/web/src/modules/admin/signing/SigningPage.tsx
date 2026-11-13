import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Segmented } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { SigningAuthority } from "../../../shared/api/generated/model";
import {
  getListSigningAuthoritiesQueryKey,
  useGetSigningSetupHint,
  useListDictionaryItems,
  useListSigningAuthorities,
} from "../../../shared/api/generated/platform-bff";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { useFormat } from "../../../shared/lib/useFormat";
import { localName } from "../../eds/dictionaries";
import { SettingsPage } from "../settings/SettingsPage";
import { ListTable } from "../company/common";
import { AuthorityDrawer, type DrawerTarget } from "./AuthorityDrawer";
import { AuthorityStatus } from "./AuthorityStatus";
import { ResolveCheck } from "./ResolveCheck";
import type { FormValues } from "./model";
import { useBasisText } from "./useBasisText";

import "./signing.css";
import type { DataColumn } from "../../../shared/ui/DataTable/DataTable";

type Filter = "active" | "all";
const KINDS_SHOWN = 2;

/**
 * Настройки · Люди и доступ · Права подписи (SIGN-2, ADR-0024 п. 1–2, 8). Эталоны — Directum RX «Право подписи» (сотрудник,
 * основание, виды, лимит, период; право по доверенности не переживает её срок), 1С:Документооборот (замещение — отдельная
 * область), SAP release strategy (порог суммы). Реестр показывает, кто вправе подписывать; замещение прав не даёт.
 */
export function SigningPage() {
  const { t, i18n } = useTranslation("signing");
  const format = useFormat();
  const queryClient = useQueryClient();
  const basisText = useBasisText();
  const [filter, setFilter] = useState<Filter>("active");
  const [target, setTarget] = useState<DrawerTarget | null>(null);
  const list = useListSigningAuthorities({ status: filter });
  const hint = useGetSigningSetupHint();
  const kinds = useListDictionaryItems(
    "signing-kinds",
    { include_hidden: true },
    {
      query: { staleTime: 5 * 60_000 },
    },
  );
  const kindName = (code: string): string => {
    const found = kinds.data?.items.find((item) => item.code === code);
    return found ? localName(found.name, i18n.language) : t("kinds.unknown", { code });
  };
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: getListSigningAuthoritiesQueryKey() });
  };
  const director = hint.data?.director ?? null;
  const showHint = hint.data !== undefined && !hint.data.has_authorities;
  const open = (preset?: Partial<FormValues>) => {
    setTarget({ mode: "new", ...(preset ? { preset } : {}) });
  };
  const addButton = (
    <Button
      type="primary"
      onClick={() => {
        open();
      }}
    >
      {t("add")}
    </Button>
  );

  const termText = (row: SigningAuthority): string =>
    row.valid_to
      ? `${t("term.from", { date: format.date(row.valid_from) })} ${t("term.until", { date: format.date(row.valid_to) })}`
      : `${t("term.from", { date: format.date(row.valid_from) })}, ${t("term.open")}`;
  const kindsText = (row: SigningAuthority): string => {
    const shown = row.kinds.slice(0, KINDS_SHOWN).map(kindName).join(", ");
    const more = row.kinds.length - KINDS_SHOWN;
    return more > 0 ? `${shown} ${t("kinds.more", { count: more })}` : shown;
  };
  const columns: DataColumn<SigningAuthority>[] = [
    {
      id: "holder",
      header: t("col.holder"),
      width: null,
      cell: (row) => (
        <div>
          <b>{row.holder.name}</b>
          <div className="pf-hint">
            {row.holder_active ? (row.holder_position ?? "") : t("inactiveHolder")}
          </div>
        </div>
      ),
    },
    {
      id: "kinds",
      header: t("col.kinds"),
      width: null,
      cell: (row) => kindsText(row),
    },
    {
      id: "limit",
      header: t("col.limit"),
      width: null,
      cell: (row) =>
        row.limit ? (
          <MoneyText value={row.limit.amount} currency={row.limit.currency} />
        ) : (
          t("limit.none")
        ),
    },
    {
      id: "basis",
      header: t("col.basis"),
      width: null,
      cell: (row) => basisText(row),
    },
    {
      id: "term",
      header: t("col.term"),
      width: null,
      cell: (row) => (
        <div>
          <div>{termText(row)}</div>
          {row.status === "expiring" && row.expires_in_days !== null ? (
            <div className="pf-hint pf-sign-expires">
              {row.expires_in_days === 0
                ? t("term.today")
                : t("term.expires", { count: row.expires_in_days })}
            </div>
          ) : null}
        </div>
      ),
    },
    {
      id: "status",
      header: t("col.status"),
      width: null,
      cell: (row) => <AuthorityStatus status={row.status} />,
    },
    {
      id: "actions",
      header: t("col.actions"),
      width: 160,
      cell: (row) => (
        <Button
          type="link"
          size="small"
          aria-label={t("openNamed", { name: row.holder.name })}
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
    <SettingsPage sectionKey="signing" subtitle={t("subtitle")} extra={addButton}>
      <div className="pf-sign">
        {showHint ? (
          <Alert
            type="info"
            showIcon
            message={t("hint.title")}
            description={
              director ? t("hint.withDirector", { name: director.name }) : t("hint.noDirector")
            }
            action={
              <div className="pf-sign-hint-actions">
                {director ? (
                  <Button
                    type="primary"
                    onClick={() => {
                      open({
                        holderId: director.id,
                        basis: "charter",
                        kinds: (kinds.data?.items ?? [])
                          .filter((item) => item.active)
                          .map((item) => item.code),
                      });
                    }}
                  >
                    {t("hint.addDirector", { name: director.name })}
                  </Button>
                ) : null}
                <Button
                  onClick={() => {
                    open();
                  }}
                >
                  {director ? t("hint.other") : t("add")}
                </Button>
              </div>
            }
          />
        ) : null}
        <div className="pf-sign-toolbar">
          <Segmented<Filter>
            aria-label={t("filter.label")}
            value={filter}
            onChange={setFilter}
            options={[
              { value: "active", label: t("filter.active") },
              { value: "all", label: t("filter.all") },
            ]}
          />
        </div>
        {list.isError ? (
          <Alert type="error" showIcon role="alert" message={t("unavailable")} />
        ) : null}
        <ListTable<SigningAuthority>
          tableId="admin.signing"
          label={t("list.label")}
          data={list.data?.items ?? []}
          loading={list.isPending}
          rowKey={(row) => row.id}
          columns={columns}
          empty={{
            title: t("empty.title"),
            text: filter === "active" ? t("empty.activeText") : t("empty.text"),
            action: list.isPending ? undefined : addButton,
          }}
        />
        <ResolveCheck />
      </div>
      {target ? (
        <AuthorityDrawer
          target={target}
          kindName={kindName}
          onChanged={refresh}
          onTarget={setTarget}
          onClose={() => {
            setTarget(null);
          }}
        />
      ) : null}
    </SettingsPage>
  );
}
