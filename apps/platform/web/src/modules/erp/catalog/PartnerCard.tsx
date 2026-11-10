import { Button, Input, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../../app/auth/useAuth";
import { canEdit } from "../../../app/access";
import type { CatalogOffer, CatalogOfferSource } from "../../../shared/api/generated/model";
import {
  getGetCatalogItemQueryKey,
  getGetCatalogSupplierQueryKey,
  getListCatalogItemsQueryKey,
  getListCatalogSuppliersQueryKey,
  useGetCatalogLookups,
  useGetCatalogSupplier,
  useUpdateSupplierOffer,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { FormField, QueryState } from "../../../shared/ui/FormParts";
import { FormModal, PriceCell, ValidityTag } from "./common";
import { errorFields } from "./errors";
import { queryLabels } from "./labels";
import { HOME_CURRENCY, currencyLabel } from "../../../shared/lib/money";
import { OFFER_SOURCES } from "./kinds";
import { OfferCreateForm, OfferHistoryModal, SupplierForm } from "./supplierForms";
import { SupplierCabinetAccess } from "./SupplierCabinetAccess";

import "./catalog.css";

/**
 * Карточка партнёра: реквизиты, доступ в кабинет, цены и сроки. Живёт в «Контакты · Контрагенты» (`?partner=<id>`), в том же
 * боковом окне, что и карточка клиента; цены показываются только с правом на цены поставщиков.
 */
export function PartnerCard({ id }: { id: string }) {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const { me } = useAuth();
  const navigate = useNavigate();
  const query = useGetCatalogSupplier(id);
  const [editing, setEditing] = useState<CatalogOffer | null>(null);
  const [history, setHistory] = useState<CatalogOffer | null>(null);
  const [editCard, setEditCard] = useState(false);
  const [adding, setAdding] = useState(false);
  const editable = canEdit(me, "erp.stock");
  return (
    <QueryState query={query} labels={queryLabels(t)} level={3} compact>
      {(card) => (
        <div className="pf-cat">
          <h3 className="pf-fp-title">{card.name}</h3>
          <DefinitionList
            items={[
              { label: t("suppliers.fields.tin"), value: card.tin },
              { label: t("suppliers.fields.reg"), value: card.registration_number },
              { label: t("suppliers.fields.country"), value: card.country },
              { label: t("suppliers.fields.currency"), value: card.currency },
              {
                label: t("suppliers.fields.kind"),
                value: card.is_manufacturer ? t("suppliers.maker") : t("suppliers.dealer"),
              },
              {
                label: t("suppliers.fields.brands"),
                value: card.brands.map((b) => b.name).join(", "),
              },
              {
                label: t("suppliers.fields.madeBrands"),
                value: card.manufactured_brands.map((b) => b.name).join(", "),
              },
              { label: t("suppliers.fields.contact"), value: card.contact_person },
              { label: t("suppliers.fields.phone"), value: card.phone },
              { label: t("suppliers.fields.email"), value: card.email },
              { label: t("suppliers.fields.website"), value: card.website },
              { label: t("suppliers.fields.address"), value: card.legal_address },
            ]}
          />
          {editable ? (
            <div className="pf-cat-actions">
              <Button
                onClick={() => {
                  setEditCard(true);
                }}
              >
                {t("suppliers.edit")}
              </Button>
              {card.prices_visible ? (
                <Button
                  onClick={() => {
                    setAdding(true);
                  }}
                >
                  {t("offerCreate.open")}
                </Button>
              ) : null}
            </div>
          ) : null}
          <SupplierCabinetAccess supplierId={id} />
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
                            void navigate(`/erp/catalog?part=items&item=${offer.product.id}`);
                          }}
                        >
                          {offer.product.name}
                        </Button>
                        <span className="pf-cat-sub">{offer.product.sku}</span>
                      </td>
                      <td>
                        <PriceCell price={offer.price} />
                        <span className="pf-cat-sub">
                          {[offer.delivery_basis, t(`offerSource.${offer.source}`)]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
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
                          <div className="pf-cat-actions">
                            <Button
                              size="small"
                              aria-label={t("offers.editNamed", { name: offer.product.name })}
                              onClick={() => {
                                setEditing(offer);
                              }}
                            >
                              {t("offers.edit")}
                            </Button>
                            <Button
                              size="small"
                              aria-label={t("history.openNamed", { name: offer.product.name })}
                              onClick={() => {
                                setHistory(offer);
                              }}
                            >
                              {t("history.open")}
                            </Button>
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {history ? (
            <OfferHistoryModal
              supplierId={id}
              offer={history}
              onClose={() => {
                setHistory(null);
              }}
            />
          ) : null}
          {editCard ? (
            <SupplierForm
              supplier={card}
              onClose={() => {
                setEditCard(false);
              }}
              onSaved={() => {
                setEditCard(false);
              }}
            />
          ) : null}
          {adding ? (
            <OfferCreateForm
              supplier={card}
              onClose={() => {
                setAdding(false);
              }}
            />
          ) : null}
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
  const [basis, setBasis] = useState<string | null>(offer.delivery_basis);
  const [leadText, setLeadText] = useState(offer.lead_time);
  const [source, setSource] = useState<CatalogOfferSource>(offer.source);
  const ids = {
    basis: useId(),
    leadText: useId(),
    source: useId(),
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
        ...(basis !== offer.delivery_basis ? { delivery_basis: basis } : {}),
        ...(leadText.trim() !== offer.lead_time ? { lead_time: leadText.trim() } : {}),
        ...(source !== offer.source ? { source } : {}),
      },
    });
  };
  return (
    <FormModal
      title={t("offers.form.title", { name: offer.product.name })}
      okLabel={t("save")}
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
        <FormField id={ids.source} label={t("offerCreate.source")}>
          <Select
            id={ids.source}
            value={source}
            onChange={setSource}
            options={OFFER_SOURCES.map((s) => ({ value: s, label: t(`offerSource.${s}`) }))}
          />
        </FormField>
      </div>
      <FormField id={ids.leadText} label={t("offerCreate.lead")} hint={t("offerCreate.leadHint")}>
        <Input
          id={ids.leadText}
          maxLength={100}
          value={leadText}
          onChange={(e) => {
            setLeadText(e.target.value);
          }}
        />
      </FormField>
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
