import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, Form, InputNumber, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ChargeTemplate,
  ChargeTemplateIn,
  ChargeTemplateUpdate,
} from "../../../../shared/api/generated/model";
import {
  getListChargeTemplatesQueryKey,
  useCreateChargeTemplate,
  useDeleteChargeTemplate,
  useListChargeTemplates,
  useListChargeTypes,
  useListReferenceItems,
  useUpdateChargeTemplate,
} from "../../../../shared/api/generated/platform-bff";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { ConfirmModal, FormModal, ListTable, QueryGate, TabHeader, ReadOnlyFence } from "../common";
import { changedFields, codeLabel } from "../diff";
import { errorFields } from "../errors";

interface Values {
  delivery_basis: string;
  charge_type: string;
  default_amount: string | null;
  default_rate_percent: string | null;
  is_deduction: boolean;
  sort_order: number | null;
  is_active: boolean;
}

const EMPTY: Values = {
  delivery_basis: "",
  charge_type: "",
  default_amount: "0",
  default_rate_percent: null,
  is_deduction: false,
  sort_order: null,
  is_active: true,
};

const valuesOf = (row: ChargeTemplate): Values => ({
  delivery_basis: row.delivery_basis,
  charge_type: row.charge_type,
  default_amount: row.default_amount,
  default_rate_percent: row.default_rate_percent,
  is_deduction: row.is_deduction,
  sort_order: row.sort_order,
  is_active: row.is_active,
});

/** Статьи расхода КП по базисам поставки (ERP `crm/charge-templates`): шаблоны сумм и ставок, которые подставляются в расчёт. */
export function ChargesTab() {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const query = useListChargeTemplates();
  const [editing, setEditing] = useState<ChargeTemplate | "new" | null>(null);
  const [removing, setRemoving] = useState<ChargeTemplate | null>(null);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: getListChargeTemplatesQueryKey() });
  const remove = useDeleteChargeTemplate({
    mutation: {
      onSuccess: () => {
        void refresh();
        setRemoving(null);
        void message.success(t("charges.deleted"));
      },
    },
  });
  const add = (
    <Button
      type="primary"
      onClick={() => {
        setEditing("new");
      }}
    >
      {t("charges.add")}
    </Button>
  );

  return (
    <div className="pf-co-body">
      <TabHeader title={t("charges.title")} hint={t("charges.hint")} />
      <ReadOnlyFence>
        <QueryGate query={query}>
          {({ items }) => (
            <>
              {items.length > 0 ? <div>{add}</div> : null}
              <ListTable<ChargeTemplate>
                label={t("charges.title")}
                data={items}
                rowKey={(row) => row.id}
                empty={{
                  title: t("charges.empty.title"),
                  text: t("charges.empty.text"),
                  action: add,
                }}
                columns={[
                  { title: t("charges.basis"), dataIndex: "delivery_basis_name" },
                  { title: t("charges.type"), dataIndex: "charge_type_name" },
                  {
                    title: t("charges.amount"),
                    dataIndex: "default_amount",
                    align: "right",
                    render: (value: string) => <span className="pf-num">{value}</span>,
                  },
                  {
                    title: t("charges.rate"),
                    dataIndex: "default_rate_percent",
                    align: "right",
                    responsive: ["md"],
                    render: (value: string | null) =>
                      value === null ? "—" : <span className="pf-num">{value} %</span>,
                  },
                  {
                    title: t("charges.deduction"),
                    dataIndex: "is_deduction",
                    responsive: ["md"],
                    render: (value: boolean) => (value ? t("yes") : t("no")),
                  },
                  {
                    title: t("status"),
                    dataIndex: "is_active",
                    render: (value: boolean) => (
                      <StatusTag tone={value ? "green" : "default"}>
                        {value ? t("active") : t("inactive")}
                      </StatusTag>
                    ),
                  },
                  {
                    title: t("actions"),
                    key: "actions",
                    render: (_: unknown, row) => {
                      const name = `${row.charge_type_name} · ${row.delivery_basis}`;
                      return (
                        <span className="pf-co-actions">
                          <Button
                            type="link"
                            size="small"
                            aria-label={t("editNamed", { name })}
                            onClick={() => {
                              setEditing(row);
                            }}
                          >
                            {t("edit")}
                          </Button>
                          <Button
                            type="link"
                            size="small"
                            danger
                            aria-label={t("deleteNamed", { name })}
                            onClick={() => {
                              remove.reset();
                              setRemoving(row);
                            }}
                          >
                            {t("delete")}
                          </Button>
                        </span>
                      );
                    },
                  },
                ]}
              />
            </>
          )}
        </QueryGate>
      </ReadOnlyFence>
      {editing !== null ? (
        <ChargeModal
          row={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
          onSaved={() => {
            void refresh();
            setEditing(null);
            void message.success(t("saved"));
          }}
        />
      ) : null}
      <ConfirmModal
        open={removing !== null}
        title={t("charges.deleteTitle", { name: removing?.charge_type_name ?? "" })}
        okLabel={t("delete")}
        danger
        loading={remove.isPending}
        error={remove.error}
        items={[t("charges.consequence.delete"), t("charges.consequence.issued")]}
        onOk={() => {
          if (removing) remove.mutate({ id: removing.id });
        }}
        onCancel={() => {
          setRemoving(null);
        }}
      />
    </div>
  );
}

function ChargeModal({
  row,
  onClose,
  onSaved,
}: {
  row: ChargeTemplate | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation("company");
  const formId = useId();
  const [form] = Form.useForm<Values>();
  const initial = row ? valuesOf(row) : EMPTY;
  const bases = useListReferenceItems("delivery-basis");
  const types = useListChargeTypes();
  const create = useCreateChargeTemplate({ mutation: { onSuccess: onSaved } });
  const update = useUpdateChargeTemplate({ mutation: { onSuccess: onSaved } });
  const mutation = row ? update : create;

  const submit = (values: Values) => {
    const onError = (error: unknown) => {
      form.setFields(
        errorFields(error)
          .filter((name) => name in EMPTY)
          .map((name) => ({ name: name as keyof Values, errors: [t("charges.invalidField")] })),
      );
    };
    if (row) {
      update.mutate(
        { id: row.id, data: changedFields(initial, values) as ChargeTemplateUpdate },
        { onError },
      );
    } else {
      const { sort_order, default_amount, ...rest } = values;
      const data: ChargeTemplateIn = {
        ...rest,
        ...(default_amount !== null ? { default_amount } : {}),
        ...(sort_order !== null ? { sort_order } : {}),
      };
      create.mutate({ data }, { onError });
    }
  };

  return (
    <FormModal
      open
      title={row ? t("charges.editTitle") : t("charges.addTitle")}
      formId={formId}
      submitLabel={t("save")}
      saving={mutation.isPending}
      error={
        mutation.error && errorFields(mutation.error).length === 0 ? mutation.error : undefined
      }
      onCancel={onClose}
    >
      <Form<Values>
        id={formId}
        form={form}
        layout="vertical"
        initialValues={initial}
        onFinish={submit}
      >
        <Form.Item
          name="delivery_basis"
          label={t("charges.basis")}
          rules={[{ required: true, message: t("required") }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            loading={bases.isPending}
            options={(bases.data?.items ?? []).map((b) => ({
              value: b.code,
              label: codeLabel(b.code, b.name),
            }))}
          />
        </Form.Item>
        <Form.Item
          name="charge_type"
          label={t("charges.type")}
          rules={[{ required: true, message: t("required") }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            loading={types.isPending}
            options={(types.data?.items ?? []).map((c) => ({ value: c.code, label: c.name }))}
          />
        </Form.Item>
        <div className="pf-co-grid">
          <Form.Item name="default_amount" label={t("charges.amount")}>
            <InputNumber stringMode min="0" step="0.01" style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name="default_rate_percent"
            label={t("charges.rate")}
            extra={t("charges.rateHint")}
          >
            <InputNumber stringMode min="0" max="100" step="0.01" style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="sort_order" label={t("charges.order")}>
            <InputNumber precision={0} style={{ width: "100%" }} />
          </Form.Item>
        </div>
        <Form.Item name="is_deduction" valuePropName="checked" style={{ marginBottom: 4 }}>
          <Checkbox>{t("charges.deductionLabel")}</Checkbox>
        </Form.Item>
        <Form.Item name="is_active" valuePropName="checked" style={{ marginBottom: 0 }}>
          <Checkbox>{t("charges.activeLabel")}</Checkbox>
        </Form.Item>
      </Form>
    </FormModal>
  );
}
