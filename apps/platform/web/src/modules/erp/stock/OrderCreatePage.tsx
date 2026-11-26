import { App, Button, Card, Form, Input, InputNumber, Radio, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import {
  useCreateSupplierOrder,
  useCreateSupplierOrderFromRequest,
  useListSupplierOrders,
  useSearchCalcCatalog,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { DateField } from "../../../shared/ui/DateField";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { CompanyPicker, useApplyCompanyRole, type PickedCompany } from "../../../shared/ui/pickers";
import { StepSections } from "../../../shared/ui/StepSections/StepSections";
import { useLeftSteps } from "../../../shared/ui/StepSections/useLeftSteps";
import { clean, orderPath, useErrorText, useRefreshStock } from "./api";
import { MIN_QUANTITY, orderRequirements } from "./orderModel";
import { PageFrame } from "../../../shared/ui/PageFrame";

interface LineValues {
  product_id?: string;
  quantity?: number;
  unit_price?: string;
}

interface Values {
  /** Партнёр заказа — компания из поля выбора; в ERP уходит её id */
  supplier: PickedCompany | null;
  mode: "manual" | "shortage";
  request?: string;
  expected_date?: string;
  note?: string;
  partner_note?: string;
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

/** Адрес страницы нового заказа: объект `new` раздела «Склад» (номер заказа так не называется) */
export const NEW_ORDER_PATH = "/erp/stock/new";
const ORDERS_PATH = "/erp/stock?view=orders";

type SectionKey = "supplier" | "lines";

/**
 * Новый заказ поставщику (черновик): вручную по строкам каталога или на дефицит заявки/проекта. Страница с секциями
 * (platform-frontend.md §4.1a): «Партнёр и способ», «Строки» (только для ручного заказа). Черновик наружу не уходит —
 * секции «Проверка» нет, «Создать черновик» в конце последней секции.
 */
export function OrderCreatePage() {
  const { t } = useTranslation("stock");
  useDocumentTitle(t("create.title"));
  // Цены в строках — только при праве на цены (как в списке заказов)
  const rights = useListSupplierOrders({});
  const prices = rights.data?.rights.prices ?? false;
  const [active, setActive] = useState<SectionKey>("supplier");
  const { left } = useLeftSteps(active);
  const { message } = App.useApp();
  const navigate = useNavigate();
  const refresh = useRefreshStock();
  const errorText = useErrorText();
  const applyRole = useApplyCompanyRole();
  const [form] = Form.useForm<Values>();
  // Строка «Мои задачи» «Заказать недостающее» открывает страницу с `?mode=shortage&request=ПР-…` (СЦ-9).
  const [params] = useSearchParams();
  const requestFromUrl = params.get("request")?.trim().slice(0, 40) ?? "";
  const initialValues: Partial<Values> =
    params.get("mode") === "shortage"
      ? { mode: "shortage", lines: [{}], ...(requestFromUrl ? { request: requestFromUrl } : {}) }
      : { mode: "manual", lines: [{}] };
  const mode = Form.useWatch("mode", form);
  const done = (number: string) => {
    refresh();
    void message.success(t("create.done", { number }));
    void navigate(orderPath(number), { replace: true });
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
  const watchedSupplier: PickedCompany | null | undefined = Form.useWatch("supplier", form);
  const supplierId = watchedSupplier?.id;
  const supplierName = watchedSupplier?.name;
  // до первой отрисовки строк useWatch отдаёт undefined
  const watchedLines: LineValues[] | undefined = Form.useWatch("lines", form);
  const lines = (watchedLines ?? []).filter((l) => l.product_id);
  const manual = mode !== "shortage";
  // Галочки шагов и их требования — из одной проверки (`orderRequirements`), а не руками на каждом шаге; текст — тот же,
  // что у правил полей формы.
  const watchedRequest: string | undefined = Form.useWatch("request", form);
  const missing = orderRequirements({
    supplierId,
    manual,
    request: watchedRequest,
    lines: watchedLines ?? [],
  });
  const needs = (key: "supplier" | "lines") =>
    missing[key].map((requirement) => t(`create.${requirement}Required`));
  return (
    <PageFrame layout="object">
      <div className="pf-stock-new">
        <PageHeader
          title={t("create.title")}
          extra={<LinkButton to={ORDERS_PATH}>{t("common.cancel")}</LinkButton>}
        />
        <Card>
          <Form<Values>
            form={form}
            layout="vertical"
            initialValues={initialValues}
            onFinishFailed={({ errorFields }) => {
              // Ошибка открывает свою секцию (§4.1a): строки — во второй
              setActive(errorFields.some((f) => f.name[0] === "lines") ? "lines" : "supplier");
            }}
            onFinish={(values) => {
              void (async () => {
                // роль поставщика — в момент сохранения: закрытая форма не оставляет роль без заказа
                const refused = await applyRole(values.supplier);
                if (refused) {
                  void message.error(refused);
                  setActive("supplier");
                  return;
                }
                if (values.mode === "shortage") {
                  fromRequest.mutate({
                    data: {
                      request: (values.request ?? "").trim(),
                      supplier_id: values.supplier?.id ?? "",
                    },
                  });
                  return;
                }
                const note = clean(values.note);
                const partnerNote = clean(values.partner_note);
                create.mutate({
                  data: {
                    supplier_id: values.supplier?.id ?? "",
                    ...(values.expected_date ? { expected_date: values.expected_date } : {}),
                    ...(note ? { note } : {}),
                    ...(partnerNote ? { partner_note: partnerNote } : {}),
                    lines: (values.lines ?? [])
                      .filter((l) => l.product_id && l.quantity)
                      .map((l) => ({
                        product_id: l.product_id ?? "",
                        quantity: l.quantity ?? 1,
                        ...(clean(l.unit_price) ? { unit_price: clean(l.unit_price) } : {}),
                      })),
                  },
                });
              })();
            }}
          >
            <StepSections
              active={active}
              onActiveChange={(key) => {
                setActive(key as SectionKey);
              }}
              sections={[
                {
                  key: "supplier",
                  title: t("create.sections.supplier"),
                  summary: [supplierName, t(manual ? "create.modeManual" : "create.modeShortage")]
                    .filter(Boolean)
                    .join(" · "),
                  complete: true,
                  requirements: needs("supplier"),
                  showRequirements: left.has("supplier"),
                  content: (
                    <>
                      <Form.Item
                        name="supplier"
                        label={t("create.supplier")}
                        rules={[{ required: true, message: t("create.supplierRequired") }]}
                      >
                        {/* ЕД-6: партнёр — компания из общего поля; без роли поставщика форма ставит её сама */}
                        <CompanyPicker id="supplier" role="supplier" assignRole />
                      </Form.Item>
                      <Form.Item name="mode" label={t("create.mode")}>
                        <Radio.Group>
                          <Radio value="manual">{t("create.modeManual")}</Radio>
                          <Radio value="shortage">{t("create.modeShortage")}</Radio>
                        </Radio.Group>
                      </Form.Item>
                      {manual ? null : (
                        <Form.Item
                          name="request"
                          label={t("create.request")}
                          extra={t("create.requestHint")}
                          rules={[
                            {
                              required: true,
                              whitespace: true,
                              message: t("create.requestRequired"),
                            },
                          ]}
                        >
                          <Input maxLength={40} />
                        </Form.Item>
                      )}
                    </>
                  ),
                  ...(manual
                    ? {}
                    : {
                        footer: (
                          <Button
                            type="primary"
                            htmlType="submit"
                            loading={create.isPending || fromRequest.isPending}
                          >
                            {t("create.submit")}
                          </Button>
                        ),
                      }),
                },
                ...(manual
                  ? [
                      {
                        key: "lines",
                        title: t("create.sections.lines"),
                        summary: t("create.linesSummary", { count: lines.length }),
                        complete: true,
                        requirements: needs("lines"),
                        showRequirements: left.has("lines"),
                        content: (
                          <>
                            <div className="pf-calc-add-row">
                              <Form.Item
                                name="expected_date"
                                label={t("create.expected")}
                                extra={t("create.expectedHint")}
                              >
                                <DateField />
                              </Form.Item>
                            </div>
                            <Form.Item
                              name="note"
                              label={t("create.note")}
                              extra={t("create.noteHint")}
                            >
                              <Input maxLength={5000} />
                            </Form.Item>
                            <Form.Item
                              name="partner_note"
                              label={t("create.partnerNote")}
                              extra={t("create.partnerNoteHint")}
                            >
                              <Input.TextArea
                                maxLength={5000}
                                autoSize={{ minRows: 2, maxRows: 6 }}
                              />
                            </Form.Item>
                            <Form.List name="lines">
                              {(fields, { add, remove }) => (
                                <div className="pf-calc-stack">
                                  {fields.map((field, index) => (
                                    <div key={field.key} className="pf-stock-line-row">
                                      <Form.Item
                                        name={[field.name, "product_id"]}
                                        label={index === 0 ? t("create.product") : undefined}
                                        rules={[
                                          { required: true, message: t("create.productRequired") },
                                        ]}
                                      >
                                        <ProductSelect
                                          label={t("create.productLabel", { n: index + 1 })}
                                        />
                                      </Form.Item>
                                      <Form.Item
                                        name={[field.name, "quantity"]}
                                        label={index === 0 ? t("create.quantity") : undefined}
                                        rules={[
                                          { required: true, message: t("create.quantityRequired") },
                                        ]}
                                      >
                                        <InputNumber
                                          min={MIN_QUANTITY}
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
                        ),
                        footer: (
                          <Button
                            type="primary"
                            htmlType="submit"
                            loading={create.isPending || fromRequest.isPending}
                          >
                            {t("create.submit")}
                          </Button>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          </Form>
        </Card>
      </div>
    </PageFrame>
  );
}
