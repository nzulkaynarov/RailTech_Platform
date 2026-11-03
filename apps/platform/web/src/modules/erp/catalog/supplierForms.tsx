import { Checkbox, Input, Modal, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import type {
  CatalogOffer,
  CatalogOfferSource,
  SupplierCreate,
  SupplierDetail,
} from "../../../shared/api/generated/model";
import {
  getGetCatalogItemQueryKey,
  getGetCatalogSupplierQueryKey,
  getListCatalogItemsQueryKey,
  getListCatalogSuppliersQueryKey,
  useCreateCatalogSupplier,
  useCreateSupplierOffer,
  useGetCatalogLookups,
  useGetSupplierOfferHistory,
  useListCatalogItems,
  useUpdateCatalogSupplier,
} from "../../../shared/api/generated/platform-bff";
import { HOME_CURRENCY, currencyLabel } from "../../../shared/lib/money";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { FormField, QueryState } from "../../../shared/ui/FormParts";
import { FormModal, PriceCell } from "./common";
import { errorFields } from "./errors";
import { queryLabels } from "./labels";
import { OFFER_SOURCES } from "./kinds";
import { useDebounced } from "./useDebounced";

/**
 * Поставщик — простая карточка компании (CAT-1): название, страна, ИНН или рег. номер нерезидента, валюта цен, контакт.
 * Без анкет и статусов допуска (L0-2). Эталон — Odoo «Contact» с вкладкой «Purchase», SAP Business Partner (роль
 * «поставщик»).
 */
export function SupplierForm({
  supplier,
  onClose,
  onSaved,
}: {
  supplier?: SupplierDetail;
  onClose: () => void;
  onSaved: (supplier: SupplierDetail) => void;
}) {
  const { t } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const lookups = useGetCatalogLookups();
  const [name, setName] = useState(supplier?.name ?? "");
  const [country, setCountry] = useState<string | null>(supplier?.country_id ?? null);
  const [tin, setTin] = useState(supplier?.tin ?? "");
  const [reg, setReg] = useState(supplier?.registration_number ?? "");
  const [currency, setCurrency] = useState<string | null>(supplier?.currency ?? null);
  const [contact, setContact] = useState(supplier?.contact_person ?? "");
  const [email, setEmail] = useState(supplier?.email ?? "");
  const [phone, setPhone] = useState(supplier?.phone ?? "");
  const [maker, setMaker] = useState(supplier?.is_manufacturer ?? false);
  const ids = {
    name: useId(),
    country: useId(),
    tin: useId(),
    reg: useId(),
    currency: useId(),
    contact: useId(),
    email: useId(),
    phone: useId(),
    maker: useId(),
  };
  const done = (saved: SupplierDetail) => {
    void queryClient.invalidateQueries({ queryKey: getListCatalogSuppliersQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getGetCatalogSupplierQueryKey(saved.id) });
    onSaved(saved);
  };
  const create = useCreateCatalogSupplier({ mutation: { onSuccess: done } });
  const update = useUpdateCatalogSupplier({ mutation: { onSuccess: done } });
  const mutation = supplier ? update : create;
  const fields = errorFields(mutation.error);
  const tinValid = tin.trim() === "" || /^\d{9}$/.test(tin.trim());
  const valid = name.trim() !== "" && (tin.trim() !== "" || reg.trim() !== "") && tinValid;
  const submit = () => {
    const data: SupplierCreate = {
      name: name.trim(),
      country_id: country,
      tin: tin.trim(),
      registration_number: reg.trim(),
      currency,
      contact_person: contact.trim(),
      email: email.trim(),
      phone: phone.trim(),
      is_manufacturer: maker,
    };
    if (supplier) update.mutate({ id: supplier.id, data });
    else create.mutate({ data });
  };
  return (
    <FormModal
      title={supplier ? t("supplierForm.editTitle") : t("supplierForm.addTitle")}
      okLabel={supplier ? t("save") : t("supplierForm.add")}
      items={supplier ? [] : (t("supplierForm.steps", { returnObjects: true }) as string[])}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={!valid}
      onOk={submit}
      onCancel={onClose}
    >
      <FormField id={ids.name} label={t("supplierForm.name")}>
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
      <div className="pf-cat-form-row">
        <FormField id={ids.country} label={t("supplierForm.country")}>
          <Select
            id={ids.country}
            allowClear
            showSearch
            optionFilterProp="label"
            value={country}
            onChange={(value: string | null | undefined) => {
              setCountry(value ?? null);
            }}
            options={(lookups.data?.countries ?? []).map((c) => ({ value: c.id, label: c.name }))}
          />
        </FormField>
        <FormField id={ids.currency} label={t("supplierForm.currency")}>
          <Select
            id={ids.currency}
            allowClear
            value={currency}
            onChange={(value: string | null | undefined) => {
              setCurrency(value ?? null);
            }}
            options={(lookups.data?.currencies ?? []).map((c) => ({
              value: c.code,
              label: c.code,
            }))}
          />
        </FormField>
      </div>
      <div className="pf-cat-form-row">
        <FormField id={ids.tin} label={t("supplierForm.tin")} hint={t("supplierForm.tinHint")}>
          <Input
            id={ids.tin}
            inputMode="numeric"
            maxLength={9}
            value={tin}
            status={fields.includes("tin") || !tinValid ? "error" : undefined}
            onChange={(e) => {
              setTin(e.target.value);
            }}
          />
        </FormField>
        <FormField id={ids.reg} label={t("supplierForm.reg")} hint={t("supplierForm.regHint")}>
          <Input
            id={ids.reg}
            maxLength={64}
            value={reg}
            status={fields.includes("registration_number") ? "error" : undefined}
            onChange={(e) => {
              setReg(e.target.value);
            }}
          />
        </FormField>
      </div>
      <FormField id={ids.contact} label={t("supplierForm.contact")}>
        <Input
          id={ids.contact}
          maxLength={255}
          value={contact}
          onChange={(e) => {
            setContact(e.target.value);
          }}
        />
      </FormField>
      <div className="pf-cat-form-row">
        <FormField id={ids.email} label={t("supplierForm.email")}>
          <Input
            id={ids.email}
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
            }}
          />
        </FormField>
        <FormField id={ids.phone} label={t("supplierForm.phone")}>
          <Input
            id={ids.phone}
            type="tel"
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value);
            }}
          />
        </FormField>
      </div>
      <Checkbox
        id={ids.maker}
        checked={maker}
        onChange={(e) => {
          setMaker(e.target.checked);
        }}
      >
        {t("supplierForm.maker")}
      </Checkbox>
    </FormModal>
  );
}

/** Цена поставщика вручную (CAT-1): товар, цена и валюта, Incoterms, MOQ, срок поставки, действует с/до, источник. */
export function OfferCreateForm({
  supplier,
  onClose,
}: {
  supplier: SupplierDetail;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const lookups = useGetCatalogLookups();
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const items = useListCatalogItems({ ...(q ? { q } : {}), page: 1, page_size: 20 });
  const [product, setProduct] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState(supplier.currency ?? HOME_CURRENCY);
  const [basis, setBasis] = useState<string | null>(null);
  const [min, setMin] = useState("1");
  const [lead, setLead] = useState("");
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  const [source, setSource] = useState<CatalogOfferSource>("manual");
  const ids = {
    product: useId(),
    amount: useId(),
    currency: useId(),
    basis: useId(),
    min: useId(),
    lead: useId(),
    from: useId(),
    until: useId(),
    source: useId(),
  };
  const mutation = useCreateSupplierOffer({
    mutation: {
      onSuccess: (offer: CatalogOffer) => {
        void queryClient.invalidateQueries({
          queryKey: getGetCatalogSupplierQueryKey(supplier.id),
        });
        void queryClient.invalidateQueries({ queryKey: getListCatalogSuppliersQueryKey() });
        void queryClient.invalidateQueries({ queryKey: getListCatalogItemsQueryKey() });
        void queryClient.invalidateQueries({
          queryKey: getGetCatalogItemQueryKey(offer.product.id),
        });
        onClose();
      },
    },
  });
  const fields = errorFields(mutation.error);
  const amountValue = amount.trim().replace(",", ".");
  const valid = product !== null && /^\d+(\.\d{1,2})?$/.test(amountValue) && /^[1-9]\d*$/.test(min);
  return (
    <FormModal
      title={t("offerCreate.title", { name: supplier.name })}
      okLabel={t("offerCreate.add")}
      items={t("offerCreate.steps", { returnObjects: true }) as string[]}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={!valid}
      onOk={() => {
        mutation.mutate({
          id: supplier.id,
          data: {
            product_id: product ?? "",
            price: { amount: amountValue, currency },
            delivery_basis: basis,
            min_order_qty: Number.parseInt(min, 10),
            ...(lead.trim() ? { lead_time: lead.trim() } : {}),
            valid_from: from || null,
            valid_until: until || null,
            source,
          },
        });
      }}
      onCancel={onClose}
    >
      <FormField id={ids.product} label={t("offerCreate.product")}>
        <Select
          id={ids.product}
          showSearch
          filterOption={false}
          value={product}
          onSearch={setSearch}
          onChange={(value: string) => {
            setProduct(value);
          }}
          status={fields.includes("product_id") ? "error" : undefined}
          options={(items.data?.items ?? []).map((i) => ({
            value: i.id,
            label: `${i.name} · ${i.sku}`,
          }))}
        />
      </FormField>
      <div className="pf-cat-form-row">
        <FormField
          id={ids.amount}
          label={t("offers.form.price", { currency: currencyLabel(currency, i18n.language) })}
        >
          <Input
            id={ids.amount}
            inputMode="decimal"
            value={amount}
            status={fields.includes("price") ? "error" : undefined}
            onChange={(e) => {
              setAmount(e.target.value);
            }}
          />
        </FormField>
        <FormField id={ids.currency} label={t("offerCreate.currency")}>
          <Select
            id={ids.currency}
            value={currency}
            onChange={setCurrency}
            options={(lookups.data?.currencies ?? []).map((c) => ({
              value: c.code,
              label: c.code,
            }))}
          />
        </FormField>
      </div>
      <div className="pf-cat-form-row">
        <FormField id={ids.basis} label={t("offerCreate.basis")}>
          <Select
            id={ids.basis}
            allowClear
            value={basis}
            onChange={(value: string | null | undefined) => {
              setBasis(value ?? null);
            }}
            options={(lookups.data?.delivery_bases ?? []).map((b) => ({
              value: b.code,
              label: `${b.code} · ${b.name}`,
            }))}
          />
        </FormField>
        <FormField id={ids.min} label={t("offers.form.min")}>
          <Input
            id={ids.min}
            inputMode="numeric"
            value={min}
            onChange={(e) => {
              setMin(e.target.value);
            }}
          />
        </FormField>
      </div>
      <FormField id={ids.lead} label={t("offerCreate.lead")} hint={t("offerCreate.leadHint")}>
        <Input
          id={ids.lead}
          maxLength={100}
          value={lead}
          onChange={(e) => {
            setLead(e.target.value);
          }}
        />
      </FormField>
      <div className="pf-cat-form-row">
        <FormField id={ids.from} label={t("offers.form.validFrom")}>
          <DateField id={ids.from} value={from} onChange={setFrom} />
        </FormField>
        <FormField id={ids.until} label={t("offers.form.validUntil")}>
          <DateField
            id={ids.until}
            value={until}
            status={fields.includes("valid_until") ? "error" : undefined}
            onChange={setUntil}
          />
        </FormField>
      </div>
      <FormField id={ids.source} label={t("offerCreate.source")}>
        <Select
          id={ids.source}
          value={source}
          onChange={setSource}
          options={OFFER_SOURCES.map((s) => ({ value: s, label: t(`offerSource.${s}`) }))}
        />
      </FormField>
    </FormModal>
  );
}

/** История цены поставщика (pghistory ERP): когда, цена, срок действия, базис, источник, кто. */
export function OfferHistoryModal({
  supplierId,
  offer,
  onClose,
}: {
  supplierId: string;
  offer: CatalogOffer;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const query = useGetSupplierOfferHistory(supplierId, offer.id);
  return (
    <Modal
      open
      title={t("history.title", { name: offer.product.name })}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <QueryState query={query} labels={queryLabels(t)} level={3} compact>
        {(data) =>
          data.items.length === 0 ? (
            <p className="pf-cat-note">{t("history.empty")}</p>
          ) : (
            <div
              className="pf-fp-scroll"
              role="region"
              tabIndex={0}
              aria-label={t("history.table")}
            >
              <table className="pf-cat-offers">
                <caption className="pf-sr-only">{t("history.table")}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t("history.at")}</th>
                    <th scope="col">{t("offers.price")}</th>
                    <th scope="col">{t("offers.validUntil")}</th>
                    <th scope="col">{t("history.source")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <tr key={row.at}>
                      <td>
                        {date(row.at, "datetime")}
                        {row.by ? <span className="pf-cat-sub">{row.by}</span> : null}
                      </td>
                      <td>
                        <PriceCell price={row.price} />
                        {row.delivery_basis ? (
                          <span className="pf-cat-sub">{row.delivery_basis}</span>
                        ) : null}
                      </td>
                      <td>{row.valid_until ? date(row.valid_until) : t("offers.noLimit")}</td>
                      <td>{t(`offerSource.${row.source}`)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </QueryState>
    </Modal>
  );
}
