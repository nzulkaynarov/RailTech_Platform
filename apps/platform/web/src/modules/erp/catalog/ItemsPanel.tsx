import { App, Button, Checkbox, Drawer, Input, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../../app/auth/useAuth";
import { canEdit } from "../../../app/access";
import { useViewport } from "../../../app/shell/useViewport";
import type {
  CatalogItem,
  CatalogItemDetail,
  CatalogItemKind,
  CatalogProposal,
  ListCatalogItemsParams,
} from "../../../shared/api/generated/model";
import {
  getGetCatalogItemQueryKey,
  getListCatalogItemsQueryKey,
  useAcceptCatalogProposal,
  useCreateCatalogItem,
  useGetCatalogItem,
  useGetCatalogLookups,
  useListCatalogItems,
  useListManufacturers,
  usePublishCatalogItem,
  useRejectCatalogProposal,
  useUnpublishCatalogItem,
  useUpdateCatalogItem,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
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
import { catalogErrorText, errorFields } from "./errors";
import { useDebounced } from "./useDebounced";
import { KINDS } from "./kinds";
import { ItemDocs } from "./ItemDocs";
import { ItemPhotos } from "./ItemPhotos";
import { queryLabels } from "./labels";
import { CatalogPriceValue, DueCell, QueueSwitch, ReturnButton, ReviewBlock } from "./ReviewQueue";

export function KindTag({ kind }: { kind: CatalogItemKind }) {
  const { t } = useTranslation("catalog");
  return (
    <StatusTag kind="itemKind" status={kind}>
      {t(`kinds.${kind}`)}
    </StatusTag>
  );
}

/** Расчёт · Номенклатура: поиск и фильтр позиций, карточка в боковом окне, добавление и правка (D2-3). */
export function ItemsPanel() {
  const { t } = useTranslation("catalog");
  const { date, number } = useFormat();
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState("");
  const [kind, setKind] = useState<CatalogItemKind | undefined>(undefined);
  const [category, setCategory] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const q = useDebounced(text.trim());
  const lookups = useGetCatalogLookups();
  // CAT-1: «На одобрении» — позиции с изменениями от поставщиков; фильтр в адресе (на него ведёт отчёт загрузки).
  const pending = params.get("proposals") === "pending";
  // PART-3: очередь проверки партнёров — «Ждут проверки» (старые отправки сверху, срок и полнота в строке)
  const waiting = params.get("review") === "waiting";
  const query = useListCatalogItems({
    ...(q ? { q } : {}),
    ...(kind ? { kind } : {}),
    ...(category ? { category_id: category } : {}),
    ...(pending ? { proposals: "pending" as const } : {}),
    ...(waiting ? { review: "waiting" as const } : {}),
    page,
    page_size: PAGE_SIZE,
  } satisfies ListCatalogItemsParams);
  const selected = params.get("item");
  const searchId = useId();
  const kindId = useId();
  const categoryId = useId();
  const pendingId = useId();
  const open = (id: string | null) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set("item", id);
        else next.delete("item");
        return next;
      },
      { replace: true },
    );
  };
  const nameColumn: Column<CatalogItem> = {
    key: "name",
    title: t("items.columns.name"),
    render: (row) => (
      <>
        <Button
          type="link"
          className="pf-cat-linkbtn"
          aria-label={t("items.open", { name: row.name })}
          aria-current={selected === row.id ? "true" : undefined}
          onClick={() => {
            open(row.id);
          }}
        >
          {row.name}
        </Button>
        <span className="pf-cat-sub">{row.sku}</span>
        {waiting && row.review ? (
          <StatusTag kind="validity" status="expiring">
            {t(`queue.kind.${row.review.kind}`)}
          </StatusTag>
        ) : row.proposals_count > 0 ? (
          <StatusTag kind="validity" status="expiring">
            {t("proposals.count", { count: row.proposals_count })}
          </StatusTag>
        ) : null}
      </>
    ),
  };
  const columns: Column<CatalogItem>[] = [
    nameColumn,
    { key: "kind", title: t("items.columns.kind"), render: (row) => <KindTag kind={row.kind} /> },
    { key: "unit", title: t("items.columns.unit"), render: (row) => row.unit?.name ?? "—" },
    {
      key: "vat",
      title: t("items.columns.vat"),
      render: (row) =>
        row.vat_effective === null
          ? "—"
          : `${number(row.vat_effective)} %${row.vat_rate === null ? ` ${t("items.vatDefault")}` : ""}`,
    },
    {
      key: "category",
      title: t("items.columns.category"),
      render: (row) => row.category?.name ?? "—",
    },
    {
      key: "offers",
      title: t("items.columns.offers"),
      render: (row) =>
        row.offers_count === 0 ? (
          t("items.noOffers")
        ) : (
          <>
            {t("items.offersCount", { count: row.offers_count })}
            {row.nearest_valid_until ? (
              <span className="pf-cat-sub">
                {t("items.priceUntil", { date: date(row.nearest_valid_until) })}
              </span>
            ) : null}
          </>
        ),
    },
    {
      key: "docs",
      title: t("items.columns.docs"),
      num: true,
      render: (row) =>
        row.docs_count === 0 ? (
          "—"
        ) : (
          <Link
            className="pf-focusable"
            to={`/erp/docs?product_id=${row.id}`}
            aria-label={t("items.docsLink", { name: row.name, count: row.docs_count })}
          >
            {row.docs_count}
          </Link>
        ),
    },
  ];
  const queueColumns: Column<CatalogItem>[] = [
    {
      key: "partner",
      title: t("queue.columns.partner"),
      render: (row) => row.review?.partner?.name ?? "—",
    },
    {
      key: "sent",
      title: t("queue.columns.sent"),
      render: (row) => (row.review ? date(row.review.submitted_at, "datetime") : "—"),
    },
    {
      key: "due",
      title: t("queue.columns.due"),
      render: (row) => <DueCell item={row} />,
    },
    {
      key: "completeness",
      title: t("queue.columns.completeness"),
      num: true,
      render: (row) => (row.completeness === null ? "—" : `${String(row.completeness)} %`),
    },
  ];
  const shownColumns = waiting ? [nameColumn, ...queueColumns] : columns;
  const setWaiting = (on: boolean) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (on) next.set("review", "waiting");
        else next.delete("review");
        return next;
      },
      { replace: true },
    );
    setPage(1);
  };
  return (
    <div className="pf-cat">
      <div className="pf-cat-controls">
        <div className="pf-cat-control">
          <QueueSwitch waiting={waiting} onChange={setWaiting} />
        </div>
        <div className="pf-cat-control">
          <label htmlFor={searchId}>{t("items.search")}</label>
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
        {waiting ? null : (
          <>
            <div className="pf-cat-control">
              <label htmlFor={kindId}>{t("items.filterKind")}</label>
              <Select
                id={kindId}
                allowClear
                placeholder={t("items.anyKind")}
                style={{ width: 200 }}
                value={kind}
                onChange={(value: CatalogItemKind | undefined) => {
                  setKind(value);
                  setPage(1);
                }}
                options={KINDS.map((k) => ({ value: k, label: t(`kinds.${k}`) }))}
              />
            </div>
            <div className="pf-cat-control">
              <label htmlFor={categoryId}>{t("items.filterCategory")}</label>
              <Select
                id={categoryId}
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder={t("items.anyCategory")}
                style={{ width: 220 }}
                value={category}
                onChange={(value: string | undefined) => {
                  setCategory(value);
                  setPage(1);
                }}
                options={(lookups.data?.categories ?? []).map((c) => ({
                  value: c.id,
                  label: c.name,
                }))}
              />
            </div>
            <div className="pf-cat-control pf-cat-control-check">
              <Checkbox
                id={pendingId}
                checked={pending}
                onChange={(event) => {
                  setParams(
                    (prev) => {
                      const next = new URLSearchParams(prev);
                      if (event.target.checked) next.set("proposals", "pending");
                      else next.delete("proposals");
                      return next;
                    },
                    { replace: true },
                  );
                  setPage(1);
                }}
              >
                {t("proposals.filter")}
              </Checkbox>
            </div>
          </>
        )}
        <span className="pf-cat-spacer" />
        {canEdit(me, "erp.stock") ? (
          <Button
            type="primary"
            onClick={() => {
              setCreating(true);
            }}
          >
            {t("items.add")}
          </Button>
        ) : null}
      </div>
      <QueryState query={query} labels={queryLabels(t)} rows={PAGE_SIZE}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState
              title={waiting ? t("queue.empty.title") : t("items.empty.title")}
              text={
                waiting
                  ? q
                    ? t("items.empty.filtered")
                    : t("queue.empty.text")
                  : q || kind || category || pending
                    ? t("items.empty.filtered")
                    : t("items.empty.text")
              }
            />
          ) : (
            <>
              <DataList
                label={waiting ? t("queue.table") : t("items.table")}
                rows={data.items}
                columns={shownColumns}
                rowKey={(row) => row.id}
                selectedKey={selected}
              />
              <Pager total={data.total} page={page} onChange={setPage} />
            </>
          )
        }
      </QueryState>
      {selected ? (
        <ItemDrawer
          id={selected}
          onClose={() => {
            open(null);
          }}
        />
      ) : null}
      {creating ? (
        <ItemForm
          onClose={() => {
            setCreating(false);
          }}
          onSaved={(item) => {
            setCreating(false);
            open(item.id);
          }}
        />
      ) : null}
    </div>
  );
}

function ItemDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation("catalog");
  const { date, number } = useFormat();
  const { me } = useAuth();
  const { mobile } = useViewport();
  const query = useGetCatalogItem(id);
  const [editing, setEditing] = useState(false);
  const [, setParams] = useSearchParams();
  const item = query.data;
  const openSupplier = (supplierId: string) => {
    setParams({ part: "suppliers", supplier: supplierId });
  };
  return (
    <Drawer
      open
      width={mobile ? "100%" : 640}
      onClose={onClose}
      title={item?.name ?? t("items.card")}
    >
      <QueryState query={query} labels={queryLabels(t)} level={3} compact>
        {(card) => (
          <div className="pf-cat">
            <DefinitionList
              items={[
                { label: t("items.fields.sku"), value: card.sku },
                { label: t("items.fields.kind"), value: <KindTag kind={card.kind} /> },
                { label: t("items.fields.unit"), value: card.unit?.name },
                {
                  label: t("items.fields.vat"),
                  value:
                    card.vat_rate !== null
                      ? `${number(card.vat_rate)} %`
                      : card.vat_effective !== null
                        ? t("items.vatCompany", { rate: number(card.vat_effective) })
                        : t("items.vatNone"),
                },
                { label: t("items.fields.category"), value: card.category?.name },
                {
                  label: t("items.fields.status"),
                  value: t(`itemStatus.${card.status ?? "DRAFT"}`),
                },
                { label: t("items.fields.brand"), value: card.brand },
                { label: t("items.fields.mpn"), value: card.manufacturer_part_number },
                { label: t("items.fields.gost"), value: card.gost_drawing },
                { label: t("items.fields.hs"), value: card.hs_code },
                { label: t("items.fields.source"), value: card.source_supplier?.name },
                { label: t("catalogPrice.label"), value: <CatalogPriceValue card={card} /> },
                {
                  label: t("items.fields.origin"),
                  value: card.origin.effective
                    ? `${card.origin.effective.name}${card.origin.source === "brand" ? ` ${t("items.originBrand")}` : ""}`
                    : t("items.originNone"),
                },
                {
                  label: t("items.fields.warranty"),
                  value:
                    card.warranty.effective_months === null
                      ? t("items.warrantyNone")
                      : `${t("items.warrantyMonths", { months: card.warranty.effective_months })}${card.warranty.source === "company" ? ` ${t("items.warrantyCompany")}` : ""}`,
                },
                ...(card.warranty.terms
                  ? [{ label: t("items.warrantyTerms"), value: card.warranty.terms }]
                  : []),
              ]}
            />
            <ReviewBlock card={card} />
            {canEdit(me, "erp.stock") ? (
              <div className="pf-cat-actions">
                <Button
                  onClick={() => {
                    setEditing(true);
                  }}
                >
                  {t("items.edit")}
                </Button>
                <PublishButton card={card} />
                <ReturnButton card={card} />
              </div>
            ) : null}
            {card.status !== "PUBLISHED" && card.publish.missing.length > 0 ? (
              <p className="pf-cat-note">
                {t("publish.missing", {
                  fields: card.publish.missing
                    .map((code) => t(`publish.fields.${code}`, { defaultValue: code }))
                    .join(", "),
                })}
              </p>
            ) : null}
            <ItemPhotos card={card} editable={canEdit(me, "erp.stock")} />
            <ItemDocs card={card} editable={canEdit(me, "erp.stock")} />
            {card.proposals.length > 0 ? (
              <ProposalsList card={card} editable={canEdit(me, "erp.stock")} />
            ) : null}
            <h3 className="pf-cat-section">{t("items.offers")}</h3>
            {!card.prices_visible ? <p className="pf-cat-note">{t("offers.pricesNote")}</p> : null}
            {card.offers.length === 0 ? (
              <p className="pf-cat-note">{t("items.noOffers")}</p>
            ) : (
              <OffersTable card={card} date={date} onSupplier={openSupplier} />
            )}
            {editing ? (
              <ItemForm
                item={card}
                onClose={() => {
                  setEditing(false);
                }}
                onSaved={() => {
                  setEditing(false);
                }}
              />
            ) : null}
          </div>
        )}
      </QueryState>
    </Drawer>
  );
}

/** «Опубликовать» / «Снять с публикации»: порог полноты решает ERP (`catalog/publishing.py`). */
function PublishButton({ card }: { card: CatalogItemDetail }) {
  const { t } = useTranslation("catalog");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const done = (saved: CatalogItemDetail) => {
    queryClient.setQueryData(getGetCatalogItemQueryKey(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: getListCatalogItemsQueryKey() });
  };
  const fail = (error: unknown) => {
    void message.error(catalogErrorText(t, error));
  };
  const publish = usePublishCatalogItem({
    mutation: {
      onSuccess: (saved) => {
        done(saved);
        if (card.review?.kind === "card") void message.success(t("review.published"));
      },
      onError: fail,
    },
  });
  const unpublish = useUnpublishCatalogItem({ mutation: { onSuccess: done, onError: fail } });
  if (card.status === "PUBLISHED") {
    return (
      <Button
        loading={unpublish.isPending}
        onClick={() => {
          unpublish.mutate({ id: card.id });
        }}
      >
        {t("publish.unpublish")}
      </Button>
    );
  }
  return (
    <Button
      disabled={!card.publish.publishable}
      loading={publish.isPending}
      onClick={() => {
        publish.mutate({ id: card.id });
      }}
    >
      {t("publish.publish")}
    </Button>
  );
}

/** Изменения карточки из прайсов поставщиков (CAT-1): было → предлагается, «Принять» или «Отклонить». */
function ProposalsList({ card, editable }: { card: CatalogItemDetail; editable: boolean }) {
  const { t } = useTranslation("catalog");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const done = (saved: CatalogItemDetail) => {
    queryClient.setQueryData(getGetCatalogItemQueryKey(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: getListCatalogItemsQueryKey() });
  };
  const fail = (error: unknown) => {
    void message.error(catalogErrorText(t, error));
  };
  const accept = useAcceptCatalogProposal({ mutation: { onSuccess: done, onError: fail } });
  const reject = useRejectCatalogProposal({ mutation: { onSuccess: done, onError: fail } });
  const label = (p: CatalogProposal) => t(`proposalField.${p.field}`);
  return (
    <>
      <h3 className="pf-cat-section">{t("proposals.title")}</h3>
      <ul className="pf-cat-proposals">
        {card.proposals.map((p) => (
          <li key={p.id} className="pf-cat-proposal">
            <div>
              <strong>{label(p)}</strong>
              {p.supplier ? <span className="pf-cat-sub">{p.supplier.name}</span> : null}
            </div>
            <div className="pf-cat-proposal-values">
              <span>
                {t("proposals.current")}: {p.current || "—"}
              </span>
              <span>
                {t("proposals.proposed")}: {p.proposed}
              </span>
            </div>
            {editable ? (
              <div className="pf-cat-actions">
                <Button
                  size="small"
                  aria-label={t("proposals.acceptNamed", { field: label(p) })}
                  loading={accept.isPending && accept.variables.id === p.id}
                  onClick={() => {
                    accept.mutate({ id: p.id });
                  }}
                >
                  {t("proposals.accept")}
                </Button>
                <Button
                  size="small"
                  aria-label={t("proposals.rejectNamed", { field: label(p) })}
                  loading={reject.isPending && reject.variables.id === p.id}
                  onClick={() => {
                    reject.mutate({ id: p.id });
                  }}
                >
                  {t("proposals.reject")}
                </Button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </>
  );
}

function OffersTable({
  card,
  date,
  onSupplier,
}: {
  card: CatalogItemDetail;
  date: (value: string) => string;
  onSupplier: (id: string) => void;
}) {
  const { t } = useTranslation("catalog");
  return (
    <div className="pf-fp-scroll" role="region" tabIndex={0} aria-label={t("items.offersTable")}>
      <table className="pf-cat-offers">
        <caption className="pf-sr-only">{t("items.offersTable")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("offers.supplier")}</th>
            <th scope="col">{t("offers.price")}</th>
            <th scope="col">{t("offers.quota")}</th>
            <th scope="col">{t("offers.lead")}</th>
            <th scope="col">{t("offers.validUntil")}</th>
          </tr>
        </thead>
        <tbody>
          {card.offers.map((offer) => (
            <tr key={offer.id}>
              <td>
                <Button
                  type="link"
                  className="pf-cat-linkbtn"
                  aria-label={t("offers.openSupplier", { name: offer.supplier.name })}
                  onClick={() => {
                    onSupplier(offer.supplier.id);
                  }}
                >
                  {offer.supplier.name}
                </Button>
              </td>
              <td>
                <PriceCell price={offer.price} />
              </td>
              <td>{t("offers.quotaValue", { qty: offer.quota_qty, min: offer.min_order_qty })}</td>
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Добавление и правка позиции. Правка отправляет только изменённые поля; НДС пусто — по умолчанию компании. */
function ItemForm({
  item,
  onClose,
  onSaved,
}: {
  item?: CatalogItemDetail;
  onClose: () => void;
  onSaved: (item: CatalogItemDetail) => void;
}) {
  const { t } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const lookups = useGetCatalogLookups();
  const [name, setName] = useState(item?.name ?? "");
  const [kind, setKind] = useState<CatalogItemKind>(item?.kind ?? "stock");
  const [unit, setUnit] = useState<string | null>(item?.unit?.id ?? null);
  const [category, setCategory] = useState<string | null>(item?.category?.id ?? null);
  const [vat, setVat] = useState(item?.vat_rate ?? "");
  const [description, setDescription] = useState(item?.description ?? "");
  const [brand, setBrand] = useState<string | null>(item?.brand_id ?? null);
  const [mpn, setMpn] = useState(item?.manufacturer_part_number ?? "");
  const [hs, setHs] = useState(item?.hs_code ?? "");
  const [country, setCountry] = useState<string | null>(item?.origin.own?.id ?? null);
  const [warrantyMonths, setWarrantyMonths] = useState(
    item?.warranty.months === null || item === undefined ? "" : String(item.warranty.months),
  );
  const [warrantyTerms, setWarrantyTerms] = useState(item?.warranty.terms ?? "");
  const brands = useListManufacturers({ page: 1, page_size: 200 });
  const ids = {
    name: useId(),
    kind: useId(),
    unit: useId(),
    category: useId(),
    vat: useId(),
    text: useId(),
    brand: useId(),
    mpn: useId(),
    hs: useId(),
    country: useId(),
    wm: useId(),
    wt: useId(),
  };
  const monthsValid = /^\d{0,3}$/.test(warrantyMonths.trim()) && Number(warrantyMonths || 0) <= 600;
  const hsValid = /^(\d{2}|\d{4}|\d{6}|\d{8}|\d{10})?$/.test(hs.trim());
  const done = (saved: CatalogItemDetail) => {
    void queryClient.invalidateQueries({ queryKey: getListCatalogItemsQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getGetCatalogItemQueryKey(saved.id) });
    onSaved(saved);
  };
  const create = useCreateCatalogItem({ mutation: { onSuccess: done } });
  const update = useUpdateCatalogItem({ mutation: { onSuccess: done } });
  const mutation = item ? update : create;
  const fields = errorFields(mutation.error);
  const vatValue = vat.trim() === "" ? null : vat.trim().replace(",", ".");
  const monthsValue = warrantyMonths.trim() === "" ? null : Number(warrantyMonths.trim());
  const submit = () => {
    if (!item) {
      create.mutate({
        data: {
          name: name.trim(),
          kind,
          ...(description.trim() ? { description: description.trim() } : {}),
          ...(unit ? { unit_id: unit } : {}),
          ...(category ? { category_id: category } : {}),
          ...(vatValue !== null ? { vat_rate: vatValue } : {}),
        },
      });
      return;
    }
    const changed = {
      ...(name.trim() !== item.name ? { name: name.trim() } : {}),
      ...(kind !== item.kind ? { kind } : {}),
      ...(unit !== (item.unit?.id ?? null) ? { unit_id: unit } : {}),
      ...(category !== (item.category?.id ?? null) ? { category_id: category } : {}),
      ...(vatValue !== item.vat_rate ? { vat_rate: vatValue } : {}),
      ...(description.trim() !== item.description ? { description: description.trim() } : {}),
      ...(brand !== item.brand_id ? { brand_id: brand } : {}),
      ...(mpn.trim() !== item.manufacturer_part_number
        ? { manufacturer_part_number: mpn.trim() }
        : {}),
      ...(hs.trim() !== item.hs_code ? { hs_code: hs.trim() } : {}),
      ...(country !== (item.origin.own?.id ?? null) ? { country_of_origin_id: country } : {}),
      ...(monthsValue !== item.warranty.months ? { warranty_months: monthsValue } : {}),
      ...(warrantyTerms.trim() !== item.warranty.terms
        ? { warranty_terms: warrantyTerms.trim() }
        : {}),
    };
    if (Object.keys(changed).length === 0) {
      onClose();
      return;
    }
    update.mutate({ id: item.id, data: changed });
  };
  return (
    <FormModal
      title={item ? t("items.form.editTitle") : t("items.form.addTitle")}
      okLabel={item ? t("save") : t("items.form.add")}
      items={
        t(item ? "items.form.editSteps" : "items.form.addSteps", {
          returnObjects: true,
        }) as string[]
      }
      loading={mutation.isPending}
      error={mutation.error}
      disabled={name.trim() === "" || !hsValid || !monthsValid}
      onOk={submit}
      onCancel={onClose}
    >
      <FormField id={ids.name} label={t("items.form.name")}>
        <Input
          id={ids.name}
          value={name}
          maxLength={255}
          status={fields.includes("name") ? "error" : undefined}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
      </FormField>
      <FormField id={ids.kind} label={t("items.form.kind")} hint={t("items.form.kindHint")}>
        <Select
          id={ids.kind}
          value={kind}
          onChange={setKind}
          options={KINDS.map((k) => ({ value: k, label: t(`kinds.${k}`) }))}
        />
      </FormField>
      <div className="pf-cat-form-row">
        <FormField id={ids.unit} label={t("items.form.unit")}>
          <Select
            id={ids.unit}
            allowClear
            value={unit}
            onChange={(value: string | null | undefined) => {
              setUnit(value ?? null);
            }}
            options={(lookups.data?.units ?? []).map((u) => ({ value: u.id, label: u.name }))}
          />
        </FormField>
        <FormField id={ids.vat} label={t("items.form.vat")} hint={t("items.form.vatHint")}>
          <Input
            id={ids.vat}
            inputMode="decimal"
            value={vat}
            status={fields.includes("vat_rate") ? "error" : undefined}
            onChange={(event) => {
              setVat(event.target.value);
            }}
          />
        </FormField>
      </div>
      <FormField id={ids.category} label={t("items.form.category")}>
        <Select
          id={ids.category}
          allowClear
          showSearch
          optionFilterProp="label"
          value={category}
          onChange={(value: string | null | undefined) => {
            setCategory(value ?? null);
          }}
          options={(lookups.data?.categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
        />
      </FormField>
      {item ? (
        <>
          <div className="pf-cat-form-row">
            <FormField id={ids.brand} label={t("items.form.brand")}>
              <Select
                id={ids.brand}
                allowClear
                showSearch
                optionFilterProp="label"
                value={brand}
                status={fields.includes("brand_id") ? "error" : undefined}
                onChange={(value: string | null | undefined) => {
                  setBrand(value ?? null);
                }}
                options={(brands.data?.items ?? []).map((m) => ({ value: m.id, label: m.name }))}
              />
            </FormField>
            <FormField id={ids.mpn} label={t("items.form.mpn")}>
              <Input
                id={ids.mpn}
                maxLength={120}
                value={mpn}
                onChange={(event) => {
                  setMpn(event.target.value);
                }}
              />
            </FormField>
          </div>
          <div className="pf-cat-form-row">
            <FormField
              id={ids.country}
              label={t("items.form.country")}
              hint={
                item.origin.brand
                  ? t("items.form.countryHintBrand", { country: item.origin.brand.name })
                  : t("items.form.countryHintNone")
              }
            >
              <Select
                id={ids.country}
                allowClear
                showSearch
                optionFilterProp="label"
                value={country}
                status={fields.includes("country_of_origin_id") ? "error" : undefined}
                onChange={(value: string | null | undefined) => {
                  setCountry(value ?? null);
                }}
                options={(lookups.data?.countries ?? []).map((c) => ({
                  value: c.id,
                  label: c.name,
                }))}
              />
            </FormField>
            <FormField
              id={ids.wm}
              label={t("items.form.warrantyMonths")}
              hint={
                item.warranty.company_months === null
                  ? t("items.form.warrantyMonthsHintNone")
                  : t("items.form.warrantyMonthsHint", { months: item.warranty.company_months })
              }
            >
              <Input
                id={ids.wm}
                inputMode="numeric"
                maxLength={3}
                value={warrantyMonths}
                status={!monthsValid || fields.includes("warranty_months") ? "error" : undefined}
                onChange={(event) => {
                  setWarrantyMonths(event.target.value);
                }}
              />
            </FormField>
          </div>
          <FormField id={ids.wt} label={t("items.form.warrantyTerms")}>
            <Input.TextArea
              id={ids.wt}
              rows={2}
              value={warrantyTerms}
              maxLength={5000}
              onChange={(event) => {
                setWarrantyTerms(event.target.value);
              }}
            />
          </FormField>
          <FormField id={ids.hs} label={t("items.form.hs")} hint={t("items.form.hsHint")}>
            <Input
              id={ids.hs}
              inputMode="numeric"
              maxLength={10}
              value={hs}
              status={!hsValid || fields.includes("hs_code") ? "error" : undefined}
              onChange={(event) => {
                setHs(event.target.value);
              }}
            />
          </FormField>
        </>
      ) : null}
      <FormField id={ids.text} label={t("items.form.description")}>
        <Input.TextArea
          id={ids.text}
          rows={3}
          value={description}
          maxLength={5000}
          onChange={(event) => {
            setDescription(event.target.value);
          }}
        />
      </FormField>
    </FormModal>
  );
}
