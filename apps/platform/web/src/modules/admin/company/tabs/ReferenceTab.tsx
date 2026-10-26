import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Form, Input, InputNumber, Segmented } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ReferenceItem,
  ReferenceItemIn,
  ReferenceKind,
} from "../../../../shared/api/generated/model";
import {
  getListReferenceItemsQueryKey,
  useCreateReferenceItem,
  useDeleteReferenceItem,
  useListReferenceItems,
  useUpdateReferenceItem,
} from "../../../../shared/api/generated/platform-bff";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { ConfirmModal, FormModal, ListTable, QueryGate, TabHeader, ReadOnlyFence } from "../common";
import { changedFields, isEmptyObject, omit } from "../diff";
import { errorFields } from "../errors";

const KINDS: ReferenceKind[] = ["countries", "currencies", "units", "delivery-basis"];
const BASIS_FLAGS = [
  "seller_pays_freight",
  "seller_pays_insurance",
  "seller_pays_import",
  "seller_pays_delivery",
] as const;

type Values = Partial<Omit<ReferenceItem, "id">> & { code: string; name: string };

/** Справочники ERP, у которых есть API: страны, валюты, единицы измерения, базисы поставки (ERP `master-data/*`). */
export function ReferenceTab() {
  const { t } = useTranslation("company");
  const [kind, setKind] = useState<ReferenceKind>("countries");
  return (
    <div className="pf-co-body">
      <TabHeader title={t("reference.title")} hint={t("reference.hint")} />
      <Segmented<ReferenceKind>
        aria-label={t("reference.kind")}
        value={kind}
        onChange={setKind}
        options={KINDS.map((value) => ({ value, label: t(`reference.kinds.${value}`) }))}
      />
      <ReferenceList key={kind} kind={kind} />
      <Alert type="info" showIcon message={t("reference.noApi")} />
    </div>
  );
}

function ReferenceList({ kind }: { kind: ReferenceKind }) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const query = useListReferenceItems(kind);
  const [editing, setEditing] = useState<ReferenceItem | "new" | null>(null);
  const [removing, setRemoving] = useState<ReferenceItem | null>(null);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: getListReferenceItemsQueryKey(kind) });
  const toggle = useUpdateReferenceItem({
    mutation: {
      onSuccess: () => {
        void refresh();
        void message.success(t("saved"));
      },
    },
  });
  const remove = useDeleteReferenceItem({
    mutation: {
      onSuccess: () => {
        void refresh();
        setRemoving(null);
        void message.success(t("reference.deleted"));
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
      {t("reference.add")}
    </Button>
  );

  return (
    <ReadOnlyFence>
      <QueryGate query={query}>
        {({ items }) => (
          <>
            {items.length > 0 ? <div>{add}</div> : null}
            {toggle.isError ? (
              <Alert type="error" showIcon role="alert" message={t("errors.DEFAULT")} />
            ) : null}
            <ListTable<ReferenceItem>
              label={t(`reference.kinds.${kind}`)}
              data={items}
              rowKey={(row) => row.id}
              empty={{
                title: t("reference.empty.title"),
                text: t("reference.empty.text"),
                action: add,
              }}
              columns={[
                {
                  title: t("reference.code"),
                  dataIndex: "code",
                  render: (v: string) => <b className="pf-co-mono">{v}</b>,
                },
                { title: t("reference.name"), dataIndex: "name" },
                ...(kind === "countries"
                  ? [
                      {
                        title: t("reference.alpha2"),
                        dataIndex: "alpha2",
                        responsive: ["md" as const],
                      },
                      {
                        title: t("reference.alpha3"),
                        dataIndex: "alpha3",
                        responsive: ["md" as const],
                      },
                      {
                        title: t("reference.vat"),
                        dataIndex: "vat_rate",
                        align: "right" as const,
                        responsive: ["md" as const],
                        render: (v: string | null | undefined) => (v ? `${v} %` : "—"),
                      },
                    ]
                  : []),
                ...(kind === "currencies"
                  ? [{ title: t("reference.symbol"), dataIndex: "symbol" }]
                  : []),
                ...(kind === "delivery-basis"
                  ? [
                      {
                        title: t("reference.sellerPays"),
                        key: "pays",
                        render: (_: unknown, row: ReferenceItem) =>
                          BASIS_FLAGS.filter((f) => row[f])
                            .map((f) => t(`reference.pays.${f}`))
                            .join(", ") || "—",
                      },
                    ]
                  : []),
                {
                  title: t("reference.order"),
                  dataIndex: "sort_order",
                  align: "right" as const,
                  responsive: ["md" as const],
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
                  render: (_: unknown, row: ReferenceItem) => (
                    <span className="pf-co-actions">
                      <Button
                        type="link"
                        size="small"
                        aria-label={t("editNamed", { name: row.name })}
                        onClick={() => {
                          setEditing(row);
                        }}
                      >
                        {t("edit")}
                      </Button>
                      <Button
                        type="link"
                        size="small"
                        aria-label={t(
                          row.is_active ? "reference.disableNamed" : "reference.enableNamed",
                          { name: row.name },
                        )}
                        loading={toggle.isPending && toggle.variables.id === row.id}
                        onClick={() => {
                          toggle.mutate({ kind, id: row.id, data: { is_active: !row.is_active } });
                        }}
                      >
                        {t(row.is_active ? "reference.disable" : "reference.enable")}
                      </Button>
                      <Button
                        type="link"
                        size="small"
                        danger
                        aria-label={t("deleteNamed", { name: row.name })}
                        onClick={() => {
                          remove.reset();
                          setRemoving(row);
                        }}
                      >
                        {t("delete")}
                      </Button>
                    </span>
                  ),
                },
              ]}
            />
            {editing !== null ? (
              <ReferenceModal
                kind={kind}
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
              title={t("reference.deleteTitle", { name: removing?.name ?? "" })}
              okLabel={t("delete")}
              danger
              loading={remove.isPending}
              error={remove.error}
              items={[t("reference.consequence.delete"), t("reference.consequence.disable")]}
              onOk={() => {
                if (removing) remove.mutate({ kind, id: removing.id });
              }}
              onCancel={() => {
                setRemoving(null);
              }}
            />
          </>
        )}
      </QueryGate>
    </ReadOnlyFence>
  );
}

function ReferenceModal({
  kind,
  row,
  onClose,
  onSaved,
}: {
  kind: ReferenceKind;
  row: ReferenceItem | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation("company");
  const formId = useId();
  const [form] = Form.useForm<Values>();
  const create = useCreateReferenceItem({ mutation: { onSuccess: onSaved } });
  const update = useUpdateReferenceItem({ mutation: { onSuccess: onSaved } });
  const mutation = row ? update : create;
  const initial: Values = row
    ? omit(row, ["id"])
    : {
        code: "",
        name: "",
        is_active: true,
        ...(kind === "delivery-basis" ? { description: "" } : {}),
      };

  const submit = (values: Values) => {
    const onError = (error: unknown) => {
      form.setFields(
        errorFields(error)
          .filter((name) => name in values)
          .map((name) => ({
            name: name as keyof Values,
            errors: [t(name === "code" ? "reference.codeTaken" : "reference.invalidField")],
          })),
      );
    };
    if (row) {
      const changed = changedFields(initial, values);
      if (isEmptyObject(changed)) {
        onClose();
        return;
      }
      update.mutate({ kind, id: row.id, data: changed }, { onError });
    } else {
      const data = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== null));
      create.mutate({ kind, data: data as unknown as ReferenceItemIn }, { onError });
    }
  };

  return (
    <FormModal
      open
      title={row ? t("reference.editTitle") : t("reference.addTitle")}
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
        <div className="pf-co-grid">
          <Form.Item
            name="code"
            label={t("reference.code")}
            rules={[{ required: true, whitespace: true, message: t("required") }]}
          >
            <Input maxLength={50} className="pf-co-mono" autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="name"
            label={t("reference.name")}
            rules={[{ required: true, whitespace: true, message: t("required") }]}
          >
            <Input maxLength={255} autoComplete="off" />
          </Form.Item>
          {kind === "countries" ? (
            <>
              <Form.Item name="alpha2" label={t("reference.alpha2")}>
                <Input maxLength={2} className="pf-co-mono" autoComplete="off" />
              </Form.Item>
              <Form.Item name="alpha3" label={t("reference.alpha3")}>
                <Input maxLength={3} className="pf-co-mono" autoComplete="off" />
              </Form.Item>
              <Form.Item name="iso_numeric" label={t("reference.isoNumeric")}>
                <Input maxLength={3} inputMode="numeric" autoComplete="off" />
              </Form.Item>
              <Form.Item name="vat_rate" label={t("reference.vat")}>
                <InputNumber stringMode min="0" max="100" step="0.5" style={{ width: "100%" }} />
              </Form.Item>
            </>
          ) : null}
          {kind === "currencies" ? (
            <Form.Item name="symbol" label={t("reference.symbol")}>
              <Input maxLength={8} autoComplete="off" />
            </Form.Item>
          ) : null}
          <Form.Item name="sort_order" label={t("reference.order")}>
            <InputNumber precision={0} style={{ width: "100%" }} />
          </Form.Item>
        </div>
        {kind === "delivery-basis" ? (
          <>
            <Form.Item name="description" label={t("reference.description")}>
              <Input.TextArea rows={2} />
            </Form.Item>
            <fieldset className="pf-co-fieldset">
              <legend className="pf-co-legend">{t("reference.sellerPays")}</legend>
              {BASIS_FLAGS.map((flag) => (
                <Form.Item
                  key={flag}
                  name={flag}
                  valuePropName="checked"
                  style={{ margin: "0 0 4px" }}
                >
                  <Checkbox>{t(`reference.pays.${flag}`)}</Checkbox>
                </Form.Item>
              ))}
            </fieldset>
          </>
        ) : null}
        <Form.Item name="is_active" valuePropName="checked" style={{ marginBottom: 0 }}>
          <Checkbox>{t("reference.activeLabel")}</Checkbox>
        </Form.Item>
      </Form>
    </FormModal>
  );
}
