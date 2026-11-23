import { Input, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../api/errors";
import type { CounterpartyPick, CounterpartyPickRole } from "../../api/generated/model";
import {
  searchCounterparties,
  useCreateCounterparty,
  useGetCatalogLookups,
  useSetCounterpartyRole,
} from "../../api/generated/platform-bff";
import { ErrorNote, FormField } from "../FormParts";
import { FormSheet } from "../FormSheet";

import { useCompanySearch } from "./useCompanySearch";
import "./pickers.css";

/** Значение последней строки «Завести» — это не id компании */
const CREATE = "__create__";
/** Минимум букв, после которых «Завести» предлагается по введённому тексту */
const MIN_CREATE = 2;

/** Выбранная компания: то, что форма хранит и отправляет (id), и то, что показывает (название, ИНН) */
export interface PickedCompany {
  id: string;
  name: string;
  inn: string | null;
  /** Общая почта компании — форма может подставить её, если у человека своей нет */
  email?: string | null;
  /** Клиент CRM, с которым связана компания: заявка уходит с его id, без него — с названием и ИНН */
  crmClientId?: number | null;
  /** Название страны из карточки: форма, где страна — справочник, подставляет её сразу */
  country?: string | null;
  /** Роль, которую форма поставит при сохранении (`useApplyCompanyRole`): у выбранной компании её ещё нет */
  pendingRole?: "supplier" | "manufacturer";
}

export type { CounterpartyPickRole };

const toPicked = (row: CounterpartyPick): PickedCompany => ({
  id: row.id,
  name: row.name,
  inn: row.inn,
  email: row.email,
  crmClientId: row.crm_client_id,
  country: row.country,
});

/** Строка выбора из `details.existing` ответа 409: проверяем форму, чужому телу не верим */
function existingRow(details: Record<string, unknown>): CounterpartyPick | null {
  const row = details["existing"];
  if (!row || typeof row !== "object") return null;
  const found = row as Partial<CounterpartyPick>;
  if (typeof found.id !== "string" || typeof found.name !== "string") return null;
  if (!found.roles || typeof found.roles !== "object") return null;
  return {
    id: found.id,
    name: found.name,
    inn: found.inn ?? null,
    country: found.country ?? null,
    roles: found.roles,
    crm_client_id: found.crm_client_id ?? null,
    email: found.email ?? null,
  };
}

/** Роли, которые форма может попросить у компании сама */
const isAssignable = (
  role: CounterpartyPickRole | undefined,
): role is "supplier" | "manufacturer" => role === "supplier" || role === "manufacturer";

/**
 * Роль формы ставится при сохранении формы, а не при выборе: закрытая форма не должна оставлять роль без факта.
 * Возвращает текст причины, если не вышло (нет права, компании нет в списке контрагентов, сбой), иначе `null`.
 */
export function useApplyCompanyRole(): (company: PickedCompany | null) => Promise<string | null> {
  const { t } = useTranslation("ui");
  const setRole = useSetCounterpartyRole();
  return async (company) => {
    const wanted = company?.pendingRole;
    if (!company || !wanted) return null;
    try {
      await setRole.mutateAsync({ id: company.id, data: { role: wanted, on: true } });
      return null;
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 403) return t(`picker.company.roleFailed.denied.${wanted}`);
      if (status === 404) return t("picker.company.roleFailed.notListed");
      return t("picker.company.roleFailed.other");
    }
  };
}

const ROLE_KEYS = ["client", "supplier", "manufacturer", "partner", "organization"] as const;

/**
 * Поле выбора компании (ЕД-6): поиск по названию и ИНН среди ВСЕХ контрагентов, роль в строке, роль формы поднимает
 * свои строки выше и никого не прячет. Свободного текста нет — значение есть только после выбора. Последняя строка
 * «Завести» открывает короткую форму и возвращает новую компанию в поле; такой ИНН уже есть — предлагается
 * существующая компания.
 */
export function CompanyPicker({
  id,
  value = null,
  onChange,
  role,
  allowCreate = true,
  assignRole = false,
  invalid = false,
  disabled = false,
  describedBy,
  suggest,
}: {
  /** Поле формы antd (`Form.Item`) подставляет `id`, `value` и `onChange` само */
  id?: string;
  value?: PickedCompany | null;
  onChange?: (company: PickedCompany | null) => void;
  /** Роль, которая нужна форме: компании с ней идут выше; для «Завести» — роль новой компании */
  role?: CounterpartyPickRole;
  allowCreate?: boolean;
  /**
   * Форма просит у компании роль «поставщик» или «изготовитель» (`role`): у выбранной компании без этой роли в
   * значении стоит `pendingRole`, и форма ставит роль при сохранении через `useApplyCompanyRole` (ERP, право
   * `supply.manage`) — выбор сам ничего не пишет.
   */
  assignRole?: boolean;
  invalid?: boolean;
  disabled?: boolean;
  describedBy?: string;
  /** Название из письма или файла, которого ещё нет среди выбранных: стоит в поле серым и открывает поиск по нему */
  suggest?: string;
}) {
  const { t } = useTranslation("ui");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState<string | null>(null);
  const { items, query, loading, settled } = useCompanySearch(search, role, open);

  // Выбор строки: роль формы запоминается в значении и ставится при сохранении формы (`useApplyCompanyRole`)
  const choose = (row: CounterpartyPick) => {
    const wanted = assignRole && isAssignable(role) && !row.roles[role] ? role : undefined;
    onChange?.({ ...toPicked(row), ...(wanted ? { pendingRole: wanted } : {}) });
  };

  const typed = query.length >= MIN_CREATE;
  const offerCreate = allowCreate && typed && settled;

  const rowOf = (row: CounterpartyPick) => {
    const roles = ROLE_KEYS.filter((key) => row.roles[key]).map((key) =>
      t(`picker.company.roles.${key}`),
    );
    const sub = [
      row.inn ? t("picker.company.inn", { inn: row.inn }) : t("picker.company.noInn"),
      ...roles,
      row.country,
    ]
      .filter(Boolean)
      .join(" · ");
    return {
      value: row.id,
      // в поле после выбора остаётся только название
      label: (
        <span className="pf-pick-row">
          <span className="pf-pick-row__name">{row.name}</span>
          <span className="pf-pick-row__sub">{sub}</span>
        </span>
      ),
      text: row.name,
      title: row.name,
    };
  };

  return (
    <>
      <Select<string>
        id={id}
        showSearch
        allowClear
        filterOption={false}
        disabled={disabled}
        status={invalid ? "error" : undefined}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        placeholder={suggest?.trim() || t("picker.company.placeholder")}
        value={value?.id}
        open={open}
        loading={loading}
        searchValue={search}
        optionLabelProp="text"
        notFoundContent={loading ? t("picker.searching") : t("picker.company.empty")}
        onOpenChange={(next) => {
          setOpen(next);
          // название из письма сразу становится запросом: найти компанию или завести её
          setSearch(next && !value ? (suggest?.trim() ?? "") : "");
        }}
        onSearch={setSearch}
        onClear={() => {
          onChange?.(null);
        }}
        onSelect={(picked) => {
          if (picked === CREATE) {
            setCreating(query);
            setOpen(false);
            return;
          }
          const row = items.find((item) => item.id === picked);
          if (row) choose(row);
        }}
        options={[
          // выбранная компания остаётся в списке, пока поиск её не показал, — иначе поле теряет название
          ...(value && !items.some((item) => item.id === value.id)
            ? [{ value: value.id, label: value.name, text: value.name, title: value.name }]
            : []),
          ...items.map(rowOf),
          ...(offerCreate
            ? [
                {
                  value: CREATE,
                  label: (
                    <span className="pf-pick-create">
                      {t("picker.company.create.option", { name: query })}
                    </span>
                  ),
                  text: query,
                },
              ]
            : []),
        ]}
      />
      {creating !== null ? (
        <NewCompany
          name={creating}
          role={role}
          onExisting={(row) => {
            choose(row);
            setCreating(null);
            setSearch("");
          }}
          onDone={(company) => {
            setCreating(null);
            setSearch("");
            onChange?.(company);
          }}
          onCancel={() => {
            setCreating(null);
          }}
        />
      ) : null}
    </>
  );
}

/** Роль новой компании: «поставщик» и «изготовитель» форма просит явно, всё остальное — организация */
const createRole = (role: CounterpartyPickRole | undefined) =>
  role === "supplier" || role === "manufacturer" ? role : "organization";

/** Короткая форма «Завести»: название, ИНН, страна, адрес — панель поверх формы, форма под ней не теряется. */
function NewCompany({
  name: initial,
  role,
  onExisting,
  onDone,
  onCancel,
}: {
  name: string;
  role: CounterpartyPickRole | undefined;
  /** Такой ИНН уже есть: компания выбирается, а не заводится вторая */
  onExisting: (row: CounterpartyPick) => void;
  onDone: (company: PickedCompany) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("ui");
  const [name, setName] = useState(initial);
  const [inn, setInn] = useState("");
  const [countryId, setCountryId] = useState<number | null>(null);
  const [address, setAddress] = useState("");
  const [taken, setTaken] = useState(false);
  const lookups = useGetCatalogLookups({ query: { staleTime: 300_000, retry: false } });
  const create = useCreateCounterparty({
    mutation: {
      onSuccess: (row) => {
        onDone(toPicked(row));
      },
    },
  });
  const innValid = inn.trim() === "" || /^\d{9}$/.test(inn.trim());

  // такой ИНН уже есть у компании — берём её, а не заводим вторую
  const pickExisting = async (existingId: string | undefined, known: CounterpartyPick | null) => {
    // ERP прикладывает строку компании к отказу: она может быть без роли, и в поиске её нет
    if (known) {
      onExisting(known);
      return;
    }
    const innText = inn.trim();
    const list = await searchCounterparties({ q: innText || name.trim(), limit: 20 }).catch(
      () => null,
    );
    const found =
      list?.items.find((row) => row.id === existingId) ??
      (innText ? list?.items.find((row) => row.inn === innText) : undefined);
    if (found) onExisting(found);
    else setTaken(true);
  };

  const failed = create.error && !(create.error instanceof ApiError && create.error.status === 409);
  return (
    <FormSheet
      title={t("picker.company.create.title")}
      submitLabel={t("picker.company.create.submit")}
      saving={create.isPending}
      submitDisabled={name.trim() === "" || !innValid}
      layer="drawer"
      dirty
      error={
        <ErrorNote
          message={
            taken
              ? t("picker.company.create.existsHidden")
              : failed
                ? t("picker.company.create.failed")
                : null
          }
        />
      }
      onSubmit={() => {
        setTaken(false);
        create.mutate(
          {
            data: {
              name: name.trim(),
              inn: inn.trim() || null,
              country_id: countryId,
              address: address.trim() || null,
              role: createRole(role),
            },
          },
          {
            onError: (error) => {
              if (error instanceof ApiError && error.status === 409) {
                const existing = error.details["existing_id"];
                void pickExisting(
                  typeof existing === "string" ? existing : undefined,
                  existingRow(error.details),
                );
              }
            },
          },
        );
      }}
      onCancel={onCancel}
    >
      <FormField id="pick-new-name" label={t("picker.company.create.name")}>
        <Input
          id="pick-new-name"
          value={name}
          maxLength={255}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
      </FormField>
      <FormField
        id="pick-new-inn"
        label={t("picker.company.create.inn")}
        hint={t("picker.company.create.innHint")}
      >
        <Input
          id="pick-new-inn"
          value={inn}
          maxLength={9}
          inputMode="numeric"
          status={innValid ? undefined : "error"}
          aria-invalid={!innValid || undefined}
          aria-describedby="pick-new-inn-hint"
          onChange={(e) => {
            setInn(e.target.value);
          }}
        />
      </FormField>
      <FormField id="pick-new-country" label={t("picker.company.create.country")}>
        <Select<number>
          id="pick-new-country"
          showSearch
          allowClear
          optionFilterProp="label"
          value={countryId ?? undefined}
          loading={lookups.isFetching}
          options={(lookups.data?.countries ?? []).map((c) => ({
            value: Number(c.id),
            label: c.name,
          }))}
          onChange={(next: number | undefined) => {
            setCountryId(next ?? null);
          }}
        />
      </FormField>
      <FormField id="pick-new-address" label={t("picker.company.create.address")}>
        <Input.TextArea
          id="pick-new-address"
          value={address}
          maxLength={500}
          autoSize={{ minRows: 2, maxRows: 4 }}
          onChange={(e) => {
            setAddress(e.target.value);
          }}
        />
      </FormField>
    </FormSheet>
  );
}
