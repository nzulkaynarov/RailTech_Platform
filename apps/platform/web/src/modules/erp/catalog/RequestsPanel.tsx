import { Button, Input, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../../app/auth/useAuth";
import { canEdit } from "../../../app/access";
import type { CategoryRequest } from "../../../shared/api/generated/model";
import {
  getListCatalogCategoryRequestsQueryKey,
  useCreateCatalogCategoryRequest,
  useGetCatalogLookups,
  useListCatalogCategoryRequests,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FormField, QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { DecisionModal } from "../../admin/company/tabs/CategoriesTab";
import { type Column, DataList, FormModal } from "./common";
import { errorFields } from "./errors";
import { queryLabels } from "./labels";

const TONE = { pending: "gold", approved: "green", rejected: "red" } as const;

/**
 * Расчёт · Запросы на новые категории: сотрудник с правом вести каталог просит категорию (она ничего не создаёт сама), решает
 * директор или администратор — раздел «Компания» (`company.settings`): одобрение привязывает заведённую категорию.
 */
export function RequestsPanel() {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const query = useListCatalogCategoryRequests();
  const [creating, setCreating] = useState(false);
  const [deciding, setDeciding] = useState<{
    row: CategoryRequest;
    action: "approve" | "reject";
  } | null>(null);
  const decide = canEdit(me, "company.settings");
  const columns: Column<CategoryRequest>[] = [
    {
      key: "name",
      title: t("requests.columns.name"),
      render: (row) => (
        <>
          <strong>{row.proposed_name}</strong>
          {row.parent_name ? (
            <span className="pf-cat-sub">{t("requests.under", { name: row.parent_name })}</span>
          ) : null}
        </>
      ),
    },
    { key: "why", title: t("requests.columns.why"), render: (row) => row.justification || "—" },
    {
      key: "author",
      title: t("requests.columns.author"),
      render: (row) => row.requested_by ?? "—",
    },
    { key: "date", title: t("requests.columns.created"), render: (row) => date(row.created_at) },
    {
      key: "status",
      title: t("requests.columns.status"),
      render: (row) => (
        <>
          <StatusTag tone={TONE[row.status]}>{t(`requests.status.${row.status}`)}</StatusTag>
          {row.status === "approved" && row.resulting_category_name ? (
            <span className="pf-cat-sub">{row.resulting_category_name}</span>
          ) : null}
          {row.status === "rejected" && row.review_notes ? (
            <span className="pf-cat-sub">{row.review_notes}</span>
          ) : null}
        </>
      ),
    },
    ...(decide
      ? [
          {
            key: "actions",
            title: t("actions"),
            render: (row: CategoryRequest) =>
              row.status === "pending" ? (
                <span className="pf-cat-actions">
                  <Button
                    size="small"
                    type="primary"
                    aria-label={t("requests.approveNamed", { name: row.proposed_name })}
                    onClick={() => {
                      setDeciding({ row, action: "approve" });
                    }}
                  >
                    {t("requests.approve")}
                  </Button>
                  <Button
                    size="small"
                    danger
                    aria-label={t("requests.rejectNamed", { name: row.proposed_name })}
                    onClick={() => {
                      setDeciding({ row, action: "reject" });
                    }}
                  >
                    {t("requests.reject")}
                  </Button>
                </span>
              ) : null,
          },
        ]
      : []),
  ];
  return (
    <div className="pf-cat">
      <div className="pf-cat-controls">
        <p className="pf-cat-note" style={{ flex: "1 1 320px" }}>
          {decide ? t("requests.hintDecide") : t("requests.hint")}
        </p>
        {canEdit(me, "erp.stock") ? (
          <Button
            type="primary"
            onClick={() => {
              setCreating(true);
            }}
          >
            {t("requests.add")}
          </Button>
        ) : null}
      </div>
      <QueryState query={query} labels={queryLabels(t)} rows={10}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title={t("requests.empty.title")} text={t("requests.empty.text")} />
          ) : (
            <DataList
              label={t("requests.table")}
              rows={data.items}
              columns={columns}
              rowKey={(row) => row.id}
            />
          )
        }
      </QueryState>
      {creating ? (
        <RequestForm
          onClose={() => {
            setCreating(false);
          }}
        />
      ) : null}
      {deciding ? (
        <DecisionModal
          row={deciding.row}
          action={deciding.action}
          onClose={() => {
            setDeciding(null);
            void queryClient.invalidateQueries({
              queryKey: getListCatalogCategoryRequestsQueryKey(),
            });
          }}
        />
      ) : null}
    </div>
  );
}

function RequestForm({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const lookups = useGetCatalogLookups();
  const [name, setName] = useState("");
  const [parent, setParent] = useState<string | null>(null);
  const [why, setWhy] = useState("");
  const ids = { name: useId(), parent: useId(), why: useId() };
  const mutation = useCreateCatalogCategoryRequest({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListCatalogCategoryRequestsQueryKey() });
        onClose();
      },
    },
  });
  const fields = errorFields(mutation.error);
  return (
    <FormModal
      title={t("requests.form.title")}
      okLabel={t("requests.form.ok")}
      items={t("requests.form.steps", { returnObjects: true }) as string[]}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={name.trim() === ""}
      onOk={() => {
        mutation.mutate({
          data: {
            name: name.trim(),
            ...(parent ? { parent_id: parent } : {}),
            ...(why.trim() ? { justification: why.trim() } : {}),
          },
        });
      }}
      onCancel={onClose}
    >
      <FormField id={ids.name} label={t("requests.form.name")}>
        <Input
          id={ids.name}
          value={name}
          maxLength={255}
          status={fields.includes("name") ? "error" : undefined}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
      </FormField>
      <FormField
        id={ids.parent}
        label={t("requests.form.parent")}
        hint={t("requests.form.parentHint")}
      >
        <Select
          id={ids.parent}
          allowClear
          showSearch
          optionFilterProp="label"
          value={parent}
          onChange={(v: string | null | undefined) => {
            setParent(v ?? null);
          }}
          options={(lookups.data?.categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
        />
      </FormField>
      <FormField id={ids.why} label={t("requests.form.why")} hint={t("requests.form.whyHint")}>
        <Input.TextArea
          id={ids.why}
          rows={3}
          value={why}
          maxLength={2000}
          onChange={(e) => {
            setWhy(e.target.value);
          }}
        />
      </FormField>
    </FormModal>
  );
}
