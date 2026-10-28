import { App, Button, Form, Input, InputNumber, Modal, Radio, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import {
  useCreateSupplierOrder,
  useCreateSupplierOrderFromRequest,
  useListStockSuppliers,
  useSearchCalcCatalog,
} from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { clean, orderPath, useErrorText, useRefreshStock } from "./api";

interface LineValues {
  product_id?: string;
  quantity?: number;
  unit_price?: string;
}

interface Values {
  supplier_id: string;
  mode: "manual" | "shortage";
  request?: string;
  expected_date?: string;
  note?: string;
  lines?: LineValues[];
}

function ProductSelect({
  value,
  onChange,
  label,
}: {
  value?: string;
  onChange?: (next: string) => void;
  label: string;
}) {
  const { t } = useTranslation("stock");
  const [q, setQ] = useState("");
  const query = useSearchCalcCatalog({ q: q.trim() }, { query: { enabled: q.trim().length >= 2 } });
  const options = (query.data?.items ?? [])
    .filter((item) => item.kind === "goods")
    .map((item) => ({
      value: item.id,
      label: item.article ? `${item.name} · ${item.article}` : item.name,
    }));
  return (
    <Select<string>
      showSearch
      aria-label={label}
      value={value}
      filterOption={false}
      onSearch={setQ}
      onChange={onChange}
      options={options}
      notFoundContent={
        q.trim().length < 2
          ? t("create.productHint")
          : query.isFetching
            ? t("create.productSearching")
            : t("create.productNone")
      }
      placeholder={label}
      className="pf-stock-product-select"
    />
  );
}

/** Новый заказ поставщику (черновик): вручную по строкам каталога или на дефицит заявки/проекта. */
export function OrderCreateModal({ prices, onClose }: { prices: boolean; onClose: () => void }) {
  const { t } = useTranslation("stock");
  const { message } = App.useApp();
  const navigate = useNavigate();
  const refresh = useRefreshStock();
  const errorText = useErrorText();
  const [form] = Form.useForm<Values>();
  const mode = Form.useWatch("mode", form);
  const suppliers = useListStockSuppliers();
  const done = (number: string) => {
    refresh();
    void message.success(t("create.done", { number }));
    onClose();
    void navigate(orderPath(number));
  };
  const onError = (error: unknown) => {
    void message.error(errorText(error));
  };
  const create = useCreateSupplierOrder({
    mutation: {
      onSuccess: (o) => {
        done(o.number);
      },
      onError,
    },
  });
  const fromRequest = useCreateSupplierOrderFromRequest({
    mutation: {
      onSuccess: (o) => {
        done(o.number);
      },
      onError,
    },
  });
  return (
    <Modal
      open
      width={640}
      title={t("create.title")}
      onCancel={onClose}
      destroyOnHidden
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="submit"
          type="primary"
          loading={create.isPending || fromRequest.isPending}
          onClick={() => {
            form.submit();
          }}
        >
          {t("create.submit")}
        </Button>,
      ]}
    >
      <Form<Values>
        form={form}
        layout="vertical"
        initialValues={{ mode: "manual", lines: [{}] }}
        onFinish={(values) => {
          if (values.mode === "shortage") {
            fromRequest.mutate({
              data: { request: (values.request ?? "").trim(), supplier_id: values.supplier_id },
            });
            return;
          }
          const note = clean(values.note);
          create.mutate({
            data: {
              supplier_id: values.supplier_id,
              ...(values.expected_date ? { expected_date: values.expected_date } : {}),
              ...(note ? { note } : {}),
              lines: (values.lines ?? [])
                .filter((l) => l.product_id && l.quantity)
                .map((l) => ({
                  product_id: l.product_id ?? "",
                  quantity: l.quantity ?? 1,
                  ...(clean(l.unit_price) ? { unit_price: clean(l.unit_price) } : {}),
                })),
            },
          });
        }}
      >
        <Form.Item
          name="supplier_id"
          label={t("create.supplier")}
          rules={[{ required: true, message: t("create.supplierRequired") }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            loading={suppliers.isPending}
            placeholder={t("create.supplier")}
            options={(suppliers.data?.items ?? []).map((s) => ({
              value: s.id,
              label: s.email ? s.name : `${s.name} · ${t("create.noEmail")}`,
            }))}
          />
        </Form.Item>
        <Form.Item name="mode" label={t("create.mode")}>
          <Radio.Group>
            <Radio value="manual">{t("create.modeManual")}</Radio>
            <Radio value="shortage">{t("create.modeShortage")}</Radio>
          </Radio.Group>
        </Form.Item>
        {mode === "shortage" ? (
          <Form.Item
            name="request"
            label={t("create.request")}
            extra={t("create.requestHint")}
            rules={[{ required: true, whitespace: true, message: t("create.requestRequired") }]}
          >
            <Input maxLength={40} placeholder="ЗВ-2026-097" />
          </Form.Item>
        ) : (
          <>
            <div className="pf-calc-add-row">
              <Form.Item name="expected_date" label={t("create.expected")}>
                <Input type="date" />
              </Form.Item>
              <Form.Item name="note" label={t("create.note")}>
                <Input maxLength={5000} />
              </Form.Item>
            </div>
            <Form.List name="lines">
              {(fields, { add, remove }) => (
                <div className="pf-calc-stack">
                  {fields.map((field, index) => (
                    <div key={field.key} className="pf-stock-line-row">
                      <Form.Item
                        name={[field.name, "product_id"]}
                        label={index === 0 ? t("create.product") : undefined}
                        rules={[{ required: true, message: t("create.productRequired") }]}
                      >
                        <ProductSelect label={t("create.productLabel", { n: index + 1 })} />
                      </Form.Item>
                      <Form.Item
                        name={[field.name, "quantity"]}
                        label={index === 0 ? t("create.quantity") : undefined}
                        rules={[{ required: true, message: t("create.quantityRequired") }]}
                      >
                        <InputNumber
                          min={1}
                          precision={0}
                          aria-label={t("create.quantityLabel", { n: index + 1 })}
                        />
                      </Form.Item>
                      {prices ? (
                        <Form.Item
                          name={[field.name, "unit_price"]}
                          label={index === 0 ? t("create.price") : undefined}
                        >
                          <Input
                            inputMode="decimal"
                            aria-label={t("create.priceLabel", { n: index + 1 })}
                          />
                        </Form.Item>
                      ) : null}
                      {fields.length > 1 ? (
                        <Button
                          type="text"
                          danger
                          aria-label={t("create.removeLine", { n: index + 1 })}
                          onClick={() => {
                            remove(field.name);
                          }}
                        >
                          ×
                        </Button>
                      ) : null}
                    </div>
                  ))}
                  <div>
                    <Button
                      onClick={() => {
                        add({});
                      }}
                    >
                      {t("create.addLine")}
                    </Button>
                  </div>
                </div>
              )}
            </Form.List>
          </>
        )}
      </Form>
      <Consequence items={t("create.consequence", { returnObjects: true }) as string[]} />
    </Modal>
  );
}
