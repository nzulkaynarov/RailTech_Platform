import { Button, Drawer, Input, Select } from "antd";
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
  ListCatalogItemsParams,
} from "../../../shared/api/generated/model";
import {
  getGetCatalogItemQueryKey,
  getListCatalogItemsQueryKey,
  useCreateCatalogItem,
  useGetCatalogItem,
  useGetCatalogLookups,
  useListCatalogItems,
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
import { errorFields } from "./errors";
import { useDebounced } from "./useDebounced";
import { KINDS } from "./kinds";
import { queryLabels } from "./labels";

export function KindTag({ kind }: { kind: CatalogItemKind }) {
  const { t } = useTranslation("catalog");
  return (
    <StatusTag tone={kind.startsWith("service") ? "purple" : kind === "stock" ? "green" : "blue"}>
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
  const query = useListCatalogItems({
    ...(q ? { q } : {}),
    ...(kind ? { kind } : {}),
    ...(category ? { category_id: category } : {}),
    page,
    page_size: PAGE_SIZE,
  } satisfies ListCatalogItemsParams);
  const selected = params.get("item");
  const searchId = useId();
  const kindId = useId();
  const categoryId = useId();
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
  const columns: Column<CatalogItem>[] = [
    {
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
        </>
      ),
    },
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
  return (
    <div className="pf-cat">
      <div className="pf-cat-controls">
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
            options={(lookups.data?.categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
          />
        </div>
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
      <QueryState query={query} labels={queryLabels(t)}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState
              title={t("items.empty.title")}
              text={q || kind || category ? t("items.empty.filtered") : t("items.empty.text")}
            />
          ) : (
            <>
              <DataList
                label={t("items.table")}
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
                { label: t("items.fields.gost"), value: card.gost_drawing },
                { label: t("items.fields.hs"), value: card.hs_code },
              ]}
            />
            {canEdit(me, "erp.stock") ? (
              <div className="pf-cat-actions">
                <Button
                  onClick={() => {
                    setEditing(true);
                  }}
                >
                  {t("items.edit")}
                </Button>
              </div>
            ) : null}
            <h3 className="pf-cat-section">{t("items.offers")}</h3>
            {!card.prices_visible ? <p className="pf-cat-note">{t("offers.pricesNote")}</p> : null}
            {card.offers.length === 0 ? (
              <p className="pf-cat-note">{t("items.noOffers")}</p>
            ) : (
              <OffersTable card={card} date={date} onSupplier={openSupplier} />
            )}
            <h3 className="pf-cat-section">{t("items.techDocs")}</h3>
            {card.tech_docs.length === 0 ? (
              <p className="pf-cat-note">{t("items.noDocs")}</p>
            ) : (
              <ul>
                {card.tech_docs.map((doc) => (
                  <li key={doc.id}>
                    <Link className="pf-focusable" to={`/erp/docs?doc=${doc.id}`}>
                      {doc.title}
                    </Link>{" "}
                    <span className="pf-hint">{t(`docKinds.${doc.kind}`)}</span>
                  </li>
                ))}
              </ul>
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
  const ids = {
    name: useId(),
    kind: useId(),
    unit: useId(),
    category: useId(),
    vat: useId(),
    text: useId(),
  };
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
      disabled={name.trim() === ""}
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
