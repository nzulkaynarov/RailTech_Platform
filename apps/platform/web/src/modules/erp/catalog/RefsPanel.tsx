import { Button, Input, Segmented, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
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
  useListCatalogExchangeRates,
  useListHsCodes,
  useListManufacturers,
  useUpdateHsCode,
  useUpdateManufacturer,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FormField, QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { type Column, DataList, FormModal, PAGE_SIZE, Pager } from "./common";
import { useDebounced } from "./useDebounced";
import { errorFields } from "./errors";
import { queryLabels } from "./labels";

const PARTS = ["rates", "hs", "brands"] as const;
type Part = (typeof PARTS)[number];

/**
 * Расчёт · Справочники, которые раньше вели только в Django admin ERP (B-035, Q-W13A3-1 п. 2): курсы валют, коды ТН ВЭД и
 * производители. Просмотр — любому сотруднику раздела; правка — по праву ERP (`catalog.manage`, курс — `settings.edit`).
 */
export function RefsPanel() {
  const { t } = useTranslation("catalog");
  const [part, setPart] = useState<Part>("rates");
  return (
    <div className="pf-cat">
      <Segmented
        aria-label={t("refs.parts")}
        value={part}
        onChange={(value) => {
          setPart(value);
        }}
        options={PARTS.map((p) => ({ value: p, label: t(`refs.${p}.title`) }))}
      />
      <p className="pf-cat-note">{t(`refs.${part}.hint`)}</p>
      {part === "rates" ? <RatesView /> : part === "hs" ? <HsView /> : <BrandsView />}
    </div>
  );
}

// --- курсы -----------------------------------------------------------------------------------

function RatesView() {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const { me } = useAuth();
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [entering, setEntering] = useState(false);
  const id = useId();
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
        <StatusTag tone={row.source === "MANUAL" ? "gold" : "blue"}>
          {t(`refs.rates.source.${row.source}`)}
        </StatusTag>
      ),
    },
  ];
  return (
    <>
      <div className="pf-cat-controls">
        <div className="pf-cat-control">
          <label htmlFor={id}>{t("refs.rates.filter")}</label>
          <Select
            id={id}
            allowClear
            placeholder={t("refs.rates.any")}
            style={{ width: 160 }}
            value={currency}
            onChange={(value: string | undefined) => {
              setCurrency(value);
              setPage(1);
            }}
            options={["USD", "EUR", "RUB"].map((c) => ({ value: c, label: c }))}
          />
        </div>
        <span className="pf-cat-spacer" />
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
      </div>
      <QueryState query={query} labels={queryLabels(t)}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title={t("refs.rates.empty.title")} text={t("refs.rates.empty.text")} />
          ) : (
            <>
              <DataList
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
      items={t("refs.rates.form.steps", { returnObjects: true }) as string[]}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={day === "" || rate.trim() === ""}
      onOk={() => {
        mutation.mutate({ data: { rate_date: day, rate_to_uzs: rate.trim().replace(",", ".") } });
      }}
      onCancel={onClose}
    >
      <FormField id={ids.day} label={t("refs.rates.form.date")}>
        <Input
          id={ids.day}
          type="date"
          value={day}
          status={fields.includes("rate_date") ? "error" : undefined}
          onChange={(e) => {
            setDay(e.target.value);
          }}
        />
      </FormField>
      <FormField
        id={ids.rate}
        label={t("refs.rates.form.rate")}
        hint={t("refs.rates.form.rateHint")}
      >
        <Input
          id={ids.rate}
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
          <StatusTag tone={row.is_active ? "green" : "default"}>
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
      <div className="pf-cat-controls">
        <div className="pf-cat-control">
          <label htmlFor={ids.q}>{t("refs.hs.search")}</label>
          <Input
            id={ids.q}
            type="search"
            allowClear
            value={text}
            style={{ width: 260 }}
            onChange={(e) => {
              setText(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <div className="pf-cat-control">
          <label htmlFor={ids.level}>{t("refs.hs.level")}</label>
          <Select
            id={ids.level}
            allowClear
            placeholder={t("refs.hs.anyLevel")}
            style={{ width: 160 }}
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
        </div>
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
        <span className="pf-cat-spacer" />
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
      </div>
      <QueryState query={query} labels={queryLabels(t)}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title={t("refs.hs.empty.title")} text={t("refs.hs.empty.text")} />
          ) : (
            <>
              <DataList
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
    <FormModal
      title={code ? t("refs.hs.form.editTitle", { code: code.code }) : t("refs.hs.form.addTitle")}
      okLabel={code ? t("save") : t("refs.hs.form.add")}
      items={
        t(code ? "refs.hs.form.editSteps" : "refs.hs.form.addSteps", {
          returnObjects: true,
        }) as string[]
      }
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
        <Input
          id={ids.until}
          type="date"
          value={until}
          status={fields.includes("valid_until") ? "error" : undefined}
          onChange={(e) => {
            setUntil(e.target.value);
          }}
        />
      </FormField>
    </FormModal>
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
      key: "country",
      title: t("refs.brands.columns.country"),
      render: (row) => row.country_name ?? "—",
    },
    { key: "site", title: t("refs.brands.columns.website"), render: (row) => row.website || "—" },
    {
      key: "state",
      title: t("refs.brands.columns.state"),
      render: (row) => (
        <StatusTag tone={row.is_active ? "green" : "default"}>
          {row.is_active ? t("refs.brands.active") : t("refs.brands.inactive")}
        </StatusTag>
      ),
    },
  ];
  return (
    <>
      <div className="pf-cat-controls">
        <div className="pf-cat-control">
          <label htmlFor={ids.q}>{t("refs.brands.search")}</label>
          <Input
            id={ids.q}
            type="search"
            allowClear
            value={text}
            style={{ width: 260 }}
            onChange={(e) => {
              setText(e.target.value);
              setPage(1);
            }}
          />
        </div>
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
        <span className="pf-cat-spacer" />
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
      </div>
      <QueryState query={query} labels={queryLabels(t)}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title={t("refs.brands.empty.title")} text={t("refs.brands.empty.text")} />
          ) : (
            <>
              <DataList
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
  const ids = { name: useId(), country: useId(), site: useId(), active: useId() };
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: getListManufacturersQueryKey() });
    onClose();
  };
  const create = useCreateManufacturer({ mutation: { onSuccess: done } });
  const update = useUpdateManufacturer({ mutation: { onSuccess: done } });
  const mutation = brand ? update : create;
  return (
    <FormModal
      title={brand ? t("refs.brands.form.editTitle") : t("refs.brands.form.addTitle")}
      okLabel={brand ? t("save") : t("refs.brands.form.add")}
      items={
        t(brand ? "refs.brands.form.editSteps" : "refs.brands.form.addSteps", {
          returnObjects: true,
        }) as string[]
      }
      loading={mutation.isPending}
      error={mutation.error}
      disabled={name.trim() === ""}
      onOk={() => {
        const data = {
          name: name.trim(),
          country_id: country,
          website: site.trim(),
          is_active: active,
        };
        if (brand) update.mutate({ id: brand.id, data });
        else create.mutate({ data });
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
    </FormModal>
  );
}
