import { Button, Input, Segmented, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../../app/auth/useAuth";
import { canEdit } from "../../../app/access";
import type { ExchangeRateRow, HsCode, Manufacturer } from "../../../shared/api/generated/model";
import {
  getGetFxRateQueryKey,
  getListCatalogExchangeRatesQueryKey,
  getListHsCodesQueryKey,
  getListManufacturersQueryKey,
  useCreateFxRate,
  useCreateHsCode,
  useCreateManufacturer,
  useGetCatalogLookups,
  useListCatalogCategoryRequests,
  useListCatalogExchangeRates,
  useListDictionaryItems,
  useListHsCodes,
  useListManufacturers,
  useUpdateHsCode,
  useUpdateManufacturer,
} from "../../../shared/api/generated/platform-bff";
import { HOME_CURRENCY } from "../../../shared/lib/money";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FormField, QueryState } from "../../../shared/ui/FormParts";
import { CompanyPicker, useApplyCompanyRole, type PickedCompany } from "../../../shared/ui/pickers";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { type Column, DataList, FormModal, FormPanel, PAGE_SIZE, Pager } from "./common";
import { useDebounced } from "./useDebounced";
import { errorFields } from "./errors";
import { queryLabels } from "./labels";
import { RequestsPanel } from "./RequestsPanel";
import { FilterBar, FilterField } from "../../../shared/ui/FilterBar";
import { UnitLabel } from "../../../shared/ui/UnitLabel";
import { unitOf } from "../../../shared/lib/unit";

const PARTS = ["hs", "brands", "requests"] as const;
type Part = (typeof PARTS)[number];

/**
 * Каталог · Справочники, которые раньше вели только в Django admin ERP (B-035, Q-W13A3-1 п. 2): коды ТН ВЭД, производители и
 * запросы на новые категории. Просмотр — любому сотруднику раздела; правка — по праву ERP (`catalog.manage`, курс — `settings.edit`).
 */
export function RefsPanel({ initial = "hs" }: { initial?: Part }) {
  const { t } = useTranslation("catalog");
  const [part, setPart] = useState<Part>(initial);
  const pending = useListCatalogCategoryRequests({ status: "pending" }).data?.items.length ?? 0;
  const label = (key: Part): string => {
    if (key !== "requests") return t(`refs.${key}.title`);
    return pending > 0 ? t("tabs.requestsCount", { count: pending }) : t("tabs.requests");
  };
  return (
    <div className="pf-cat">
      <Segmented
        aria-label={t("refs.parts")}
        value={part}
        onChange={(value) => {
          setPart(value);
        }}
        options={PARTS.map((p) => ({ value: p, label: label(p) }))}
      />
      {part === "requests" ? null : <p className="pf-cat-note">{t(`refs.${part}.hint`)}</p>}
      {part === "requests" ? <RequestsPanel /> : part === "hs" ? <HsView /> : <BrandsView />}
    </div>
  );
}

// --- курсы -----------------------------------------------------------------------------------

/** Курсы валют: живут в «Настройки · Налоги и валюты». Список отдаёт ERP по разделу склада. */
export function RatesView() {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const { me } = useAuth();
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [entering, setEntering] = useState(false);
  const id = useId();
  // Курс ведётся по каждой включённой валюте справочника (источник «ЦБ», решение 2026-11-11), UZS — база.
  const currencies = (useListDictionaryItems("currencies").data?.items ?? [])
    .map((item) => item.code)
    .filter((code) => code !== HOME_CURRENCY);
  const query = useListCatalogExchangeRates({
    ...(currency ? { currency } : {}),
    page,
    page_size: PAGE_SIZE,
  });
  const columns: Column<ExchangeRateRow>[] = [
    { key: "currency", title: t("refs.rates.columns.currency"), render: (row) => row.currency },
    {
      key: "rate",
      title: t("refs.rates.columns.rate"),
      num: true,
      render: (row) => row.rate_to_uzs,
    },
    { key: "date", title: t("refs.rates.columns.date"), render: (row) => date(row.rate_date) },
    {
      key: "source",
      title: t("refs.rates.columns.source"),
      render: (row) => (
        <StatusTag kind="origin" status={row.source}>
          {t(`refs.rates.source.${row.source}`)}
        </StatusTag>
      ),
    },
  ];
  return (
    <>
      <FilterBar
        tools
        actions={
          <>
            {canEdit(me, "company.settings") ? (
              <Button
                type="primary"
                onClick={() => {
                  setEntering(true);
                }}
              >
                {t("refs.rates.enter")}
              </Button>
            ) : null}
          </>
        }
      >
        <FilterField id={id} label={t("refs.rates.filter")} width={160}>
          <Select
            id={id}
            allowClear
            placeholder={t("refs.rates.any")}
            value={currency}
            onChange={(value: string | undefined) => {
              setCurrency(value);
              setPage(1);
            }}
            options={currencies.map((c) => ({ value: c, label: c }))}
          />
        </FilterField>
      </FilterBar>
      <QueryState query={query} labels={queryLabels(t)} rows={PAGE_SIZE}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title={t("refs.rates.empty.title")} text={t("refs.rates.empty.text")} />
          ) : (
            <>
              <DataList
                tableId="erp.catalog.rates"
                label={t("refs.rates.table")}
                rows={data.items}
                columns={columns}
                rowKey={(row) => row.id}
              />
              <Pager total={data.total} page={page} onChange={setPage} />
            </>
          )
        }
      </QueryState>
      {entering ? (
        <RateForm
          onClose={() => {
            setEntering(false);
          }}
        />
      ) : null}
    </>
  );
}

function RateForm({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const [day, setDay] = useState("2026-10-28");
  const [rate, setRate] = useState("");
  const ids = { day: useId(), rate: useId() };
  const mutation = useCreateFxRate({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListCatalogExchangeRatesQueryKey() });
        void queryClient.invalidateQueries({ queryKey: getGetFxRateQueryKey() });
        onClose();
      },
    },
  });
  const fields = errorFields(mutation.error);
  return (
    <FormModal
      title={t("refs.rates.form.title")}
      okLabel={t("refs.rates.form.ok")}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={day === "" || rate.trim() === ""}
      onOk={() => {
        mutation.mutate({ data: { rate_date: day, rate_to_uzs: rate.trim().replace(",", ".") } });
      }}
      onCancel={onClose}
    >
      <FormField id={ids.day} label={t("refs.rates.form.date")}>
        <DateField
          id={ids.day}
          value={day}
          status={fields.includes("rate_date") ? "error" : undefined}
          onChange={setDay}
        />
      </FormField>
      <FormField
        id={ids.rate}
        label={<UnitLabel label={t("refs.rates.form.rate")} />}
        hint={t("refs.rates.form.rateHint")}
      >
        <Input
          id={ids.rate}
          suffix={unitOf(t("refs.rates.form.rate"))}
          inputMode="decimal"
          value={rate}
          status={fields.includes("rate_to_uzs") ? "error" : undefined}
          onChange={(e) => {
            setRate(e.target.value);
          }}
        />
      </FormField>
    </FormModal>
  );
}

// --- коды ТН ВЭД -----------------------------------------------------------------------------

function HsView() {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const { me } = useAuth();
  const [text, setText] = useState("");
  const [level, setLevel] = useState<number | undefined>(undefined);
  const [active, setActive] = useState(false);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<HsCode | "new" | null>(null);
  const q = useDebounced(text.trim());
  const ids = { q: useId(), level: useId(), active: useId() };
  const query = useListHsCodes({
    ...(q ? { q } : {}),
    ...(level ? { level: level as 2 | 4 | 6 | 8 | 10 } : {}),
    ...(active ? { active: true } : {}),
    page,
    page_size: PAGE_SIZE,
  });
  const edit = canEdit(me, "erp.stock");
  const columns: Column<HsCode>[] = [
    {
      key: "code",
      title: t("refs.hs.columns.code"),
      render: (row) =>
        edit ? (
          <Button
            type="link"
            className="pf-cat-linkbtn"
            aria-label={t("refs.hs.editNamed", { code: row.code })}
            onClick={() => {
              setEditing(row);
            }}
          >
            {row.code}
          </Button>
        ) : (
          row.code
        ),
    },
    { key: "name", title: t("refs.hs.columns.name"), render: (row) => row.name },
    {
      key: "unit",
      title: t("refs.hs.columns.unit"),
      render: (row) => [row.unit_name, row.extra_unit_name].filter(Boolean).join(", ") || "—",
    },
    { key: "level", title: t("refs.hs.columns.level"), num: true, render: (row) => row.level },
    {
      key: "state",
      title: t("refs.hs.columns.state"),
      render: (row) => (
        <>
          <StatusTag kind="activity" status={row.is_active ? "active" : "inactive"}>
            {row.is_active ? t("refs.hs.active") : t("refs.hs.closed")}
          </StatusTag>
          {row.valid_until ? (
            <span className="pf-cat-sub">
              {t("refs.hs.until", { date: date(row.valid_until) })}
            </span>
          ) : null}
        </>
      ),
    },
  ];
  return (
    <>
      <FilterBar
        tools
        actions={
          <>
            {edit ? (
              <Button
                type="primary"
                onClick={() => {
                  setEditing("new");
                }}
              >
                {t("refs.hs.add")}
              </Button>
            ) : null}
          </>
        }
      >
        <FilterField id={ids.q} label={t("refs.hs.search")} grow>
          <Input
            id={ids.q}
            type="search"
            placeholder={t("refs.hs.search")}
            allowClear
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setPage(1);
            }}
          />
        </FilterField>
        <FilterField id={ids.level} label={t("refs.hs.level")} width={160}>
          <Select
            id={ids.level}
            allowClear
            placeholder={t("refs.hs.anyLevel")}
            value={level}
            onChange={(value: number | undefined) => {
              setLevel(value);
              setPage(1);
            }}
            options={[2, 4, 6, 8, 10].map((n) => ({
              value: n,
              label: t("refs.hs.digits", { count: n }),
            }))}
          />
        </FilterField>
        <label htmlFor={ids.active} className="pf-cat-check">
          <input
            id={ids.active}
            type="checkbox"
            checked={active}
            onChange={(e) => {
              setActive(e.target.checked);
              setPage(1);
            }}
          />{" "}
          {t("refs.hs.onlyActive")}
        </label>
      </FilterBar>
      <QueryState query={query} labels={queryLabels(t)} rows={PAGE_SIZE}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title={t("refs.hs.empty.title")} text={t("refs.hs.empty.text")} />
          ) : (
            <>
              <DataList
                tableId="erp.catalog.hs"
                label={t("refs.hs.table")}
                rows={data.items}
                columns={columns}
                rowKey={(row) => row.id}
              />
              <Pager total={data.total} page={page} onChange={setPage} />
            </>
          )
        }
      </QueryState>
      {editing ? (
        <HsForm
          code={editing === "new" ? undefined : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </>
  );
}

function HsForm({ code, onClose }: { code?: HsCode | undefined; onClose: () => void }) {
  const { t } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const [value, setValue] = useState(code?.code ?? "");
  const [name, setName] = useState(code?.name ?? "");
  const [unit, setUnit] = useState(code?.unit_name ?? "");
  const [extra, setExtra] = useState(code?.extra_unit_name ?? "");
  const [until, setUntil] = useState(code?.valid_until ?? "");
  const ids = { code: useId(), name: useId(), unit: useId(), extra: useId(), until: useId() };
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: getListHsCodesQueryKey() });
    onClose();
  };
  const create = useCreateHsCode({ mutation: { onSuccess: done } });
  const update = useUpdateHsCode({ mutation: { onSuccess: done } });
  const mutation = code ? update : create;
  const fields = errorFields(mutation.error);
  return (
    <FormPanel
      title={code ? t("refs.hs.form.editTitle", { code: code.code }) : t("refs.hs.form.addTitle")}
      okLabel={code ? t("save") : t("refs.hs.form.add")}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={name.trim() === "" || (!code && !/^\d+$/.test(value.trim()))}
      onOk={() => {
        const data = {
          name: name.trim(),
          unit_name: unit.trim(),
          extra_unit_name: extra.trim(),
          valid_until: until || null,
        };
        if (code) update.mutate({ id: code.id, data });
        else create.mutate({ data: { code: value.trim(), ...data } });
      }}
      onCancel={onClose}
    >
      <FormField id={ids.code} label={t("refs.hs.form.code")} hint={t("refs.hs.form.codeHint")}>
        <Input
          id={ids.code}
          inputMode="numeric"
          value={value}
          disabled={code !== undefined}
          maxLength={10}
          status={fields.includes("code") ? "error" : undefined}
          onChange={(e) => {
            setValue(e.target.value);
          }}
        />
      </FormField>
      <FormField id={ids.name} label={t("refs.hs.form.name")}>
        <Input.TextArea
          id={ids.name}
          rows={2}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
      </FormField>
      <div className="pf-cat-form-row">
        <FormField id={ids.unit} label={t("refs.hs.form.unit")}>
          <Input
            id={ids.unit}
            value={unit}
            maxLength={64}
            onChange={(e) => {
              setUnit(e.target.value);
            }}
          />
        </FormField>
        <FormField id={ids.extra} label={t("refs.hs.form.extraUnit")}>
          <Input
            id={ids.extra}
            value={extra}
            maxLength={64}
            onChange={(e) => {
              setExtra(e.target.value);
            }}
          />
        </FormField>
      </div>
      <FormField id={ids.until} label={t("refs.hs.form.until")} hint={t("refs.hs.form.untilHint")}>
        <DateField
          id={ids.until}
          value={until}
          status={fields.includes("valid_until") ? "error" : undefined}
          onChange={setUntil}
        />
      </FormField>
    </FormPanel>
  );
}

// --- производители ---------------------------------------------------------------------------

function BrandsView() {
  const { t } = useTranslation("catalog");
  const { me } = useAuth();
  const [text, setText] = useState("");
  const [inactive, setInactive] = useState(false);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Manufacturer | "new" | null>(null);
  const q = useDebounced(text.trim());
  const ids = { q: useId(), inactive: useId() };
  const edit = canEdit(me, "erp.stock");
  const query = useListManufacturers({
    ...(q ? { q } : {}),
    ...(inactive && edit ? { include_inactive: true } : {}),
    page,
    page_size: PAGE_SIZE,
  });
  // ADR-0028 п. 4: бренд — марка; изготовитель — компания с ролью «Изготовитель», на неё ссылка
  const roleNames = (codes: readonly string[]) =>
    codes
      .map((code) => t(`refs.brands.roles.${code}`, { defaultValue: "" }))
      .filter(Boolean)
      .join(", ");
  const columns: Column<Manufacturer>[] = [
    {
      key: "name",
      title: t("refs.brands.columns.name"),
      render: (row) =>
        edit ? (
          <Button
            type="link"
            className="pf-cat-linkbtn"
            aria-label={t("refs.brands.editNamed", { name: row.name })}
            onClick={() => {
              setEditing(row);
            }}
          >
            {row.name}
          </Button>
        ) : (
          row.name
        ),
    },
    {
      key: "company",
      title: t("refs.brands.columns.company"),
      render: (row) =>
        row.company_id && row.company_name ? (
          <span>
            <Link to={`/crm/clients?partner=${row.company_id}&panel=open&tab=card`}>
              {row.company_name}
            </Link>
            {row.company_roles.length ? (
              <span className="pf-hint"> · {roleNames(row.company_roles)}</span>
            ) : null}
          </span>
        ) : (
          <span className="pf-hint">{t("refs.brands.noCompany")}</span>
        ),
    },
    {
      key: "country",
      title: t("refs.brands.columns.country"),
      render: (row) => row.country_name ?? "—",
    },
    {
      key: "products",
      title: t("refs.brands.columns.products"),
      num: true,
      render: (row) => (row.products_count ?? "—").toString(),
    },
    ...(inactive
      ? [
          {
            key: "state",
            title: t("refs.brands.columns.state"),
            render: (row: Manufacturer) => (
              <StatusTag kind="activity" status={row.is_active ? "active" : "inactive"}>
                {row.is_active ? t("refs.brands.active") : t("refs.brands.inactive")}
              </StatusTag>
            ),
          },
        ]
      : []),
  ];
  return (
    <>
      <FilterBar
        tools
        actions={
          <>
            {edit ? (
              <Button
                type="primary"
                onClick={() => {
                  setEditing("new");
                }}
              >
                {t("refs.brands.add")}
              </Button>
            ) : null}
          </>
        }
      >
        <FilterField id={ids.q} label={t("refs.brands.search")} grow>
          <Input
            id={ids.q}
            type="search"
            placeholder={t("refs.brands.search")}
            allowClear
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setPage(1);
            }}
          />
        </FilterField>
        {edit ? (
          <label htmlFor={ids.inactive} className="pf-cat-check">
            <input
              id={ids.inactive}
              type="checkbox"
              checked={inactive}
              onChange={(e) => {
                setInactive(e.target.checked);
                setPage(1);
              }}
            />{" "}
            {t("refs.brands.showInactive")}
          </label>
        ) : null}
      </FilterBar>
      <QueryState query={query} labels={queryLabels(t)} rows={PAGE_SIZE}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title={t("refs.brands.empty.title")} text={t("refs.brands.empty.text")} />
          ) : (
            <>
              <DataList
                tableId="erp.catalog.brands"
                label={t("refs.brands.table")}
                rows={data.items}
                columns={columns}
                rowKey={(row) => row.id}
              />
              <Pager total={data.total} page={page} onChange={setPage} />
            </>
          )
        }
      </QueryState>
      {editing ? (
        <BrandForm
          brand={editing === "new" ? undefined : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </>
  );
}

function BrandForm({ brand, onClose }: { brand?: Manufacturer | undefined; onClose: () => void }) {
  const { t } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const lookups = useGetCatalogLookups();
  const [name, setName] = useState(brand?.name ?? "");
  const [country, setCountry] = useState<string | null>(brand?.country_id ?? null);
  const [site, setSite] = useState(brand?.website ?? "");
  const [active, setActive] = useState(brand?.is_active ?? true);
  // Изготовитель — любая компания из контрагентов (ЕД-6); без роли форма ставит ей «изготовитель» сама
  const [company, setCompany] = useState<PickedCompany | null>(
    brand?.company_id && brand.company_name
      ? { id: brand.company_id, name: brand.company_name, inn: null }
      : null,
  );
  const ids = {
    name: useId(),
    country: useId(),
    site: useId(),
    active: useId(),
    company: useId(),
  };
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: getListManufacturersQueryKey() });
    onClose();
  };
  const applyRole = useApplyCompanyRole();
  const [roleRefused, setRoleRefused] = useState<string | null>(null);
  const create = useCreateManufacturer({ mutation: { onSuccess: done } });
  const update = useUpdateManufacturer({ mutation: { onSuccess: done } });
  const mutation = brand ? update : create;
  return (
    <FormPanel
      title={brand ? t("refs.brands.form.editTitle") : t("refs.brands.form.addTitle")}
      okLabel={brand ? t("save") : t("refs.brands.form.add")}
      loading={mutation.isPending}
      error={roleRefused ?? mutation.error}
      disabled={name.trim() === ""}
      onOk={() => {
        const data = {
          name: name.trim(),
          country_id: country,
          website: site.trim(),
          is_active: active,
          company_id: company?.id ?? null,
        };
        setRoleRefused(null);
        // роль изготовителя — в момент сохранения: закрытая форма не оставляет роль без бренда
        void applyRole(company).then((refused) => {
          if (refused) {
            setRoleRefused(refused);
            return;
          }
          if (brand) update.mutate({ id: brand.id, data });
          else create.mutate({ data });
        });
      }}
      onCancel={onClose}
    >
      <FormField id={ids.name} label={t("refs.brands.form.name")}>
        <Input
          id={ids.name}
          value={name}
          maxLength={255}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
      </FormField>
      <FormField
        id={ids.company}
        label={t("refs.brands.form.company")}
        hint={t("refs.brands.form.companyHint")}
      >
        <CompanyPicker
          id={ids.company}
          role="manufacturer"
          assignRole
          value={company}
          onChange={(picked) => {
            setCompany(picked);
            setRoleRefused(null);
            // страна — из карточки компании сразу; в справочнике нет такого названия — остаётся прежняя
            const own = (lookups.data?.countries ?? []).find((c) => c.name === picked?.country);
            if (own) setCountry(own.id);
          }}
        />
      </FormField>
      <FormField id={ids.country} label={t("refs.brands.form.country")}>
        <Select
          id={ids.country}
          allowClear
          showSearch
          optionFilterProp="label"
          value={country}
          onChange={(v: string | null | undefined) => {
            setCountry(v ?? null);
          }}
          options={(lookups.data?.countries ?? []).map((c) => ({ value: c.id, label: c.name }))}
        />
      </FormField>
      <FormField id={ids.site} label={t("refs.brands.form.website")}>
        <Input
          id={ids.site}
          value={site}
          maxLength={200}
          onChange={(e) => {
            setSite(e.target.value);
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
        {t("refs.brands.form.active")}
      </label>
    </FormPanel>
  );
}
