import { Button, Drawer, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../../app/auth/useAuth";
import { canEdit } from "../../../app/access";
import { useViewport } from "../../../app/shell/useViewport";
import type { CatalogOffer, SupplierRow } from "../../../shared/api/generated/model";
import {
  getGetCatalogItemQueryKey,
  getGetCatalogSupplierQueryKey,
  getListCatalogItemsQueryKey,
  getListCatalogSuppliersQueryKey,
  useGetCatalogLookups,
  useGetCatalogSupplier,
  useListCatalogSuppliers,
  useUpdateSupplierOffer,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FormField, QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import {
  type Column,
  DataList,
  FormModal,
  PAGE_SIZE,
  Pager,
  PriceCell,
  ValidityTag,
} from "./common";
import { errorFields } from "./errors";
import { useDebounced } from "./useDebounced";
import { queryLabels } from "./labels";
import { HOME_CURRENCY, currencyLabel } from "../../../shared/lib/money";

/** Расчёт · Поставщики: квоты, сроки действия цен и, с правом на цены поставщиков, сами цены (D2-3). */
export function SuppliersPanel() {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState("");
  const [page, setPage] = useState(1);
  const q = useDebounced(text.trim());
  const searchId = useId();
  const query = useListCatalogSuppliers({ ...(q ? { q } : {}), page, page_size: PAGE_SIZE });
  const selected = params.get("supplier");
  const select = (id: string | null) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set("supplier", id);
        else next.delete("supplier");
        return next;
      },
      { replace: true },
    );
  };
  const columns: Column<SupplierRow>[] = [
    {
      key: "name",
      title: t("suppliers.columns.name"),
      render: (row) => (
        <>
          <Button
            type="link"
            className="pf-cat-linkbtn"
            aria-label={t("suppliers.open", { name: row.name })}
            aria-current={selected === row.id ? "true" : undefined}
            onClick={() => {
              select(row.id);
            }}
          >
            {row.name}
          </Button>
          <span className="pf-cat-sub">
            {[row.tin && t("suppliers.tin", { tin: row.tin }), row.country]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </>
      ),
    },
    {
      key: "offers",
      title: t("suppliers.columns.offers"),
      num: true,
      render: (row) => row.offers_count,
    },
    {
      key: "terms",
      title: t("suppliers.columns.terms"),
      render: (row) => (
        <>
          {row.expired_count > 0 ? (
            <StatusTag kind="validity" status="expired">
              {t("suppliers.expired", { count: row.expired_count })}
            </StatusTag>
          ) : null}{" "}
          {row.expiring_count > 0 ? (
            <StatusTag kind="validity" status="expiring">
              {t("suppliers.expiring", { count: row.expiring_count })}
            </StatusTag>
          ) : null}
          {row.expired_count === 0 && row.expiring_count === 0 ? (
            <StatusTag kind="validity" status="ok">
              {t("suppliers.allValid")}
            </StatusTag>
          ) : null}
          {row.nearest_valid_until ? (
            <span className="pf-cat-sub">
              {t("suppliers.nearest", { date: date(row.nearest_valid_until) })}
            </span>
          ) : null}
        </>
      ),
    },
  ];
  return (
    <div className="pf-cat">
      <div className="pf-cat-controls">
        <div className="pf-cat-control">
          <label htmlFor={searchId}>{t("suppliers.search")}</label>
          <Input
            id={searchId}
            type="search"
            allowClear
            value={text}
            style={{ width: 280 }}
            onChange={(event) => {
              setText(event.target.value);
              setPage(1);
            }}
          />
        </div>
      </div>
      <QueryState query={query} labels={queryLabels(t)} rows={PAGE_SIZE}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState
              title={t("suppliers.empty.title")}
              text={q ? t("suppliers.empty.filtered") : t("suppliers.empty.text")}
            />
          ) : (
            <>
              <DataList
                label={t("suppliers.table")}
                rows={data.items}
                columns={columns}
                rowKey={(row) => row.id}
                selectedKey={selected}
              />
              <Pager total={data.total} page={page} onChange={setPage} />
            </>
          )
        }
      </QueryState>
      {selected ? (
        <SupplierDrawer
          id={selected}
          onClose={() => {
            select(null);
          }}
        />
      ) : null}
    </div>
  );
}

function SupplierDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const { me } = useAuth();
  const { mobile } = useViewport();
  const query = useGetCatalogSupplier(id);
  const [editing, setEditing] = useState<CatalogOffer | null>(null);
  const [, setParams] = useSearchParams();
  return (
    <Drawer
      open
      width={mobile ? "100%" : 680}
      onClose={onClose}
      title={query.data?.name ?? t("suppliers.card")}
    >
      <QueryState query={query} labels={queryLabels(t)} level={3} compact>
        {(card) => (
          <div className="pf-cat">
            <DefinitionList
              items={[
                { label: t("suppliers.fields.tin"), value: card.tin },
                { label: t("suppliers.fields.country"), value: card.country },
                { label: t("suppliers.fields.contact"), value: card.contact_person },
                { label: t("suppliers.fields.phone"), value: card.phone },
                { label: t("suppliers.fields.email"), value: card.email },
                { label: t("suppliers.fields.website"), value: card.website },
                { label: t("suppliers.fields.address"), value: card.legal_address },
              ]}
            />
            <h3 className="pf-cat-section">{t("suppliers.offers")}</h3>
            {!card.prices_visible ? <p className="pf-cat-note">{t("offers.pricesNote")}</p> : null}
            {card.offers.length === 0 ? (
              <p className="pf-cat-note">{t("suppliers.noOffers")}</p>
            ) : (
              <div
                className="pf-fp-scroll"
                role="region"
                tabIndex={0}
                aria-label={t("suppliers.offersTable")}
              >
                <table className="pf-cat-offers">
                  <caption className="pf-sr-only">{t("suppliers.offersTable")}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{t("offers.product")}</th>
                      <th scope="col">{t("offers.price")}</th>
                      <th scope="col">{t("offers.quota")}</th>
                      <th scope="col">{t("offers.lead")}</th>
                      <th scope="col">{t("offers.validUntil")}</th>
                      {canEdit(me, "erp.stock") ? <th scope="col">{t("actions")}</th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {card.offers.map((offer) => (
                      <tr key={offer.id}>
                        <td>
                          <Button
                            type="link"
                            className="pf-cat-linkbtn"
                            aria-label={t("offers.openProduct", { name: offer.product.name })}
                            onClick={() => {
                              setParams({ part: "items", item: offer.product.id });
                            }}
                          >
                            {offer.product.name}
                          </Button>
                          <span className="pf-cat-sub">{offer.product.sku}</span>
                        </td>
                        <td>
                          <PriceCell price={offer.price} />
                        </td>
                        <td>
                          {t("offers.quotaValue", {
                            qty: offer.quota_qty,
                            min: offer.min_order_qty,
                          })}
                        </td>
                        <td>
                          {t("offers.leadValue", {
                            stock: offer.in_stock_lead_days,
                            order: offer.order_lead_days,
                          })}
                        </td>
                        <td>
                          {offer.valid_until ? date(offer.valid_until) : t("offers.noLimit")}{" "}
                          <ValidityTag validity={offer.validity} />
                          {!offer.is_active ? (
                            <span className="pf-cat-sub">{t("offers.inactive")}</span>
                          ) : null}
                        </td>
                        {canEdit(me, "erp.stock") ? (
                          <td>
                            <Button
                              size="small"
                              aria-label={t("offers.editNamed", { name: offer.product.name })}
                              onClick={() => {
                                setEditing(offer);
                              }}
                            >
                              {t("offers.edit")}
                            </Button>
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {editing ? (
              <OfferForm
                supplierId={id}
                offer={editing}
                pricesVisible={card.prices_visible}
                onClose={() => {
                  setEditing(null);
                }}
              />
            ) : null}
          </div>
        )}
      </QueryState>
    </Drawer>
  );
}

/** Условия предложения: квота, минимальный заказ, сроки поставки, окно действия цены; цена — только с правом на цены. */
function OfferForm({
  supplierId,
  offer,
  pricesVisible,
  onClose,
}: {
  supplierId: string;
  offer: CatalogOffer;
  pricesVisible: boolean;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const lookups = useGetCatalogLookups();
  const [amount, setAmount] = useState(offer.price?.amount ?? "");
  const [quota, setQuota] = useState(String(offer.quota_qty));
  const [min, setMin] = useState(String(offer.min_order_qty));
  const [stockLead, setStockLead] = useState(String(offer.in_stock_lead_days));
  const [orderLead, setOrderLead] = useState(String(offer.order_lead_days));
  const [from, setFrom] = useState(offer.valid_from ?? "");
  const [until, setUntil] = useState(offer.valid_until ?? "");
  const [active, setActive] = useState(offer.is_active);
  const ids = {
    amount: useId(),
    quota: useId(),
    min: useId(),
    stock: useId(),
    order: useId(),
    from: useId(),
    until: useId(),
    active: useId(),
  };
  const mutation = useUpdateSupplierOffer({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getGetCatalogSupplierQueryKey(supplierId) });
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
  const whole = (value: string) => Number.parseInt(value, 10);
  const valid =
    [quota, stockLead, orderLead].every((v) => /^\d+$/.test(v.trim())) &&
    /^[1-9]\d*$/.test(min.trim());
  const currency = offer.price?.currency ?? lookups.data?.currencies[0]?.code ?? HOME_CURRENCY;
  const submit = () => {
    const price = pricesVisible && amount.trim() !== (offer.price?.amount ?? "");
    mutation.mutate({
      id: supplierId,
      offerId: offer.id,
      data: {
        ...(price ? { price: { amount: amount.trim().replace(",", "."), currency } } : {}),
        quota_qty: whole(quota),
        min_order_qty: whole(min),
        in_stock_lead_days: whole(stockLead),
        order_lead_days: whole(orderLead),
        valid_from: from || null,
        valid_until: until || null,
        is_active: active,
      },
    });
  };
  return (
    <FormModal
      title={t("offers.form.title", { name: offer.product.name })}
      okLabel={t("save")}
      items={t("offers.form.steps", { returnObjects: true }) as string[]}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={!valid}
      onOk={submit}
      onCancel={onClose}
    >
      {pricesVisible ? (
        <FormField
          id={ids.amount}
          label={t("offers.form.price", { currency: currencyLabel(currency, i18n.language) })}
        >
          <Input
            id={ids.amount}
            inputMode="decimal"
            value={amount}
            status={fields.includes("price") ? "error" : undefined}
            onChange={(event) => {
              setAmount(event.target.value);
            }}
          />
        </FormField>
      ) : (
        <p className="pf-cat-note">{t("offers.form.noPrice")}</p>
      )}
      <div className="pf-cat-form-row">
        <FormField id={ids.quota} label={t("offers.form.quota")} hint={t("offers.form.quotaHint")}>
          <Input
            id={ids.quota}
            inputMode="numeric"
            value={quota}
            onChange={(e) => {
              setQuota(e.target.value);
            }}
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
      <div className="pf-cat-form-row">
        <FormField id={ids.stock} label={t("offers.form.stockLead")}>
          <Input
            id={ids.stock}
            inputMode="numeric"
            value={stockLead}
            onChange={(e) => {
              setStockLead(e.target.value);
            }}
          />
        </FormField>
        <FormField id={ids.order} label={t("offers.form.orderLead")}>
          <Input
            id={ids.order}
            inputMode="numeric"
            value={orderLead}
            onChange={(e) => {
              setOrderLead(e.target.value);
            }}
          />
        </FormField>
      </div>
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
      <label htmlFor={ids.active} className="pf-cat-check">
        <input
          id={ids.active}
          type="checkbox"
          checked={active}
          onChange={(e) => {
            setActive(e.target.checked);
          }}
        />{" "}
        {t("offers.form.active")}
      </label>
    </FormModal>
  );
}
