import { Button, Input, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../../app/auth/useAuth";
import { canEdit } from "../../../app/access";
import type { Brigade, BrigadeKind } from "../../../shared/api/generated/model";
import {
  getListBrigadesQueryKey,
  useCreateBrigade,
  useGetCatalogLookups,
  useListBrigades,
  useUpdateBrigade,
} from "../../../shared/api/generated/platform-bff";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FormField, QueryState } from "../../../shared/ui/FormParts";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { type Column, DataList, FormModal, PAGE_SIZE, Pager } from "./common";
import { useDebounced } from "./useDebounced";
import { errorFields } from "./errors";
import { queryLabels } from "./labels";

const KINDS: readonly BrigadeKind[] = ["brigade", "person", "subcontractor"];

/** Расчёт · Бригады и исполнители услуг: ставка видна держателю зоны услуг расчёта или `cost_margin` (D2-3). */
export function BrigadesPanel() {
  const { t } = useTranslation("catalog");
  const { me } = useAuth();
  const [text, setText] = useState("");
  const [page, setPage] = useState(1);
  const [inactive, setInactive] = useState(false);
  const [editing, setEditing] = useState<Brigade | "new" | null>(null);
  const q = useDebounced(text.trim());
  const searchId = useId();
  const inactiveId = useId();
  const query = useListBrigades({
    ...(q ? { q } : {}),
    ...(inactive ? { include_inactive: true } : {}),
    page,
    page_size: PAGE_SIZE,
  });
  const edit = canEdit(me, "erp.stock");
  const columns: Column<Brigade>[] = [
    {
      key: "name",
      title: t("brigades.columns.name"),
      render: (row) =>
        edit ? (
          <Button
            type="link"
            className="pf-cat-linkbtn"
            aria-label={t("brigades.editNamed", { name: row.name })}
            onClick={() => {
              setEditing(row);
            }}
          >
            {row.name}
          </Button>
        ) : (
          <span>{row.name}</span>
        ),
    },
    {
      key: "kind",
      title: t("brigades.columns.kind"),
      render: (row) => (
        <>
          {t(`brigadeKinds.${row.kind}`)}
          {!row.is_active ? (
            <span className="pf-cat-sub">
              <StatusTag tone="default">{t("brigades.inactive")}</StatusTag>
            </span>
          ) : null}
        </>
      ),
    },
    {
      key: "headcount",
      title: t("brigades.columns.headcount"),
      num: true,
      render: (row) => row.headcount,
    },
    {
      key: "spec",
      title: t("brigades.columns.specialization"),
      render: (row) => row.specialization || "—",
    },
    {
      key: "rate",
      title: t("brigades.columns.rate"),
      render: (row) =>
        row.rate ? (
          <>
            <MoneyText
              value={row.rate.amount}
              {...(row.rate.currency && row.rate.currency !== "UZS"
                ? { currency: row.rate.currency }
                : {})}
            />{" "}
            <span className="pf-hint">{t(`rateUnits.${row.rate.unit}`)}</span>
          </>
        ) : row.rate_visible ? (
          "—"
        ) : (
          <span className="pf-hint">{t("brigades.rateHidden")}</span>
        ),
    },
  ];
  return (
    <div className="pf-cat">
      <div className="pf-cat-controls">
        <div className="pf-cat-control">
          <label htmlFor={searchId}>{t("brigades.search")}</label>
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
        <label htmlFor={inactiveId} className="pf-cat-check">
          <input
            id={inactiveId}
            type="checkbox"
            checked={inactive}
            onChange={(event) => {
              setInactive(event.target.checked);
              setPage(1);
            }}
          />{" "}
          {t("brigades.showInactive")}
        </label>
        <span className="pf-cat-spacer" />
        {edit ? (
          <Button
            type="primary"
            onClick={() => {
              setEditing("new");
            }}
          >
            {t("brigades.add")}
          </Button>
        ) : null}
      </div>
      <QueryState query={query} labels={queryLabels(t)} rows={PAGE_SIZE}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState
              title={t("brigades.empty.title")}
              text={q ? t("brigades.empty.filtered") : t("brigades.empty.text")}
            />
          ) : (
            <>
              {!data.items.some((b) => b.rate_visible) ? (
                <p className="pf-cat-note">{t("brigades.ratesNote")}</p>
              ) : null}
              <DataList
                label={t("brigades.table")}
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
        <BrigadeForm
          brigade={editing === "new" ? undefined : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}

function BrigadeForm({ brigade, onClose }: { brigade?: Brigade | undefined; onClose: () => void }) {
  const { t } = useTranslation("catalog");
  const queryClient = useQueryClient();
  const lookups = useGetCatalogLookups();
  const rateAllowed = brigade ? brigade.rate_visible : true;
  const [name, setName] = useState(brigade?.name ?? "");
  const [kind, setKind] = useState<BrigadeKind>(brigade?.kind ?? "brigade");
  const [headcount, setHeadcount] = useState(String(brigade?.headcount ?? 1));
  const [specialization, setSpecialization] = useState(brigade?.specialization ?? "");
  const [amount, setAmount] = useState(brigade?.rate?.amount ?? "");
  const [unit, setUnit] = useState<"day" | "hour">(brigade?.rate?.unit ?? "day");
  const [note, setNote] = useState(brigade?.note ?? "");
  const [active, setActive] = useState(brigade?.is_active ?? true);
  const ids = {
    name: useId(),
    kind: useId(),
    head: useId(),
    spec: useId(),
    rate: useId(),
    unit: useId(),
    note: useId(),
    active: useId(),
  };
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: getListBrigadesQueryKey() });
    onClose();
  };
  const create = useCreateBrigade({ mutation: { onSuccess: done } });
  const update = useUpdateBrigade({ mutation: { onSuccess: done } });
  const mutation = brigade ? update : create;
  const fields = errorFields(mutation.error);
  const currency = brigade?.rate?.currency ?? lookups.data?.currencies[0]?.code ?? "UZS";
  const rateValue = amount.trim().replace(",", ".");
  const validCount = /^[1-9]\d{0,2}$/.test(headcount.trim());
  const submit = () => {
    const rate =
      rateAllowed && rateValue !== ""
        ? { rate: { amount: rateValue, currency }, rate_unit: unit }
        : rateAllowed && brigade?.rate
          ? { rate: null }
          : {};
    const data = {
      name: name.trim(),
      kind,
      specialization: specialization.trim(),
      headcount: Number.parseInt(headcount, 10),
      note: note.trim(),
      is_active: active,
      ...rate,
    };
    if (brigade) update.mutate({ id: brigade.id, data });
    else create.mutate({ data });
  };
  return (
    <FormModal
      title={brigade ? t("brigades.form.editTitle") : t("brigades.form.addTitle")}
      okLabel={brigade ? t("save") : t("brigades.form.add")}
      items={
        t(brigade ? "brigades.form.editSteps" : "brigades.form.addSteps", {
          returnObjects: true,
        }) as string[]
      }
      loading={mutation.isPending}
      error={mutation.error}
      disabled={name.trim() === "" || !validCount}
      onOk={submit}
      onCancel={onClose}
    >
      <FormField id={ids.name} label={t("brigades.form.name")}>
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
        <FormField id={ids.kind} label={t("brigades.form.kind")}>
          <Select
            id={ids.kind}
            value={kind}
            onChange={setKind}
            options={KINDS.map((k) => ({ value: k, label: t(`brigadeKinds.${k}`) }))}
          />
        </FormField>
        <FormField id={ids.head} label={t("brigades.form.headcount")}>
          <Input
            id={ids.head}
            inputMode="numeric"
            value={headcount}
            status={fields.includes("headcount") ? "error" : undefined}
            onChange={(e) => {
              setHeadcount(e.target.value);
            }}
          />
        </FormField>
      </div>
      <FormField id={ids.spec} label={t("brigades.form.specialization")}>
        <Input
          id={ids.spec}
          value={specialization}
          maxLength={255}
          onChange={(e) => {
            setSpecialization(e.target.value);
          }}
        />
      </FormField>
      {rateAllowed ? (
        <div className="pf-cat-form-row">
          <FormField
            id={ids.rate}
            label={t("brigades.form.rate", { currency })}
            hint={t("brigades.form.rateHint")}
          >
            <Input
              id={ids.rate}
              inputMode="decimal"
              value={amount}
              status={fields.includes("rate") ? "error" : undefined}
              onChange={(e) => {
                setAmount(e.target.value);
              }}
            />
          </FormField>
          <FormField id={ids.unit} label={t("brigades.form.unit")}>
            <Select
              id={ids.unit}
              value={unit}
              onChange={setUnit}
              options={[
                { value: "day", label: t("rateUnits.day") },
                { value: "hour", label: t("rateUnits.hour") },
              ]}
            />
          </FormField>
        </div>
      ) : (
        <p className="pf-cat-note">{t("brigades.form.noRate")}</p>
      )}
      <FormField id={ids.note} label={t("brigades.form.note")}>
        <Input
          id={ids.note}
          value={note}
          maxLength={500}
          onChange={(e) => {
            setNote(e.target.value);
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
        {t("brigades.form.active")}
      </label>
    </FormModal>
  );
}
