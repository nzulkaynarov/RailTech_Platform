import { AutoComplete, Input, Select } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import {
  useCreateEdsAddressee,
  useListEdsAddresseePeople,
  useSearchEdsAddressees,
} from "../../../shared/api/generated/platform-bff";
import type {
  EdsAddressee,
  EdsAddresseePeopleItemsItem,
} from "../../../shared/api/generated/model";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { FormSheet } from "../../../shared/ui/FormSheet";

/** Сколько букв нужно, чтобы искать по контрагентам (как в контракте `GET /eds/addressees`) */
const MIN_QUERY = 2;
/** Значение строки «Завести организацию» среди подсказок — не id контрагента */
const CREATE = "__create__";

/**
 * «Организация» письма (пункт «Ш»): ввод с подсказками из контрагентов — клиентов, партнёров и организаций ERP по
 * названию или ИНН. Выбор подставляет ИНН, почту и «Кому» организации. Адресата нет среди контрагентов — последняя
 * строка подсказок заводит его организацией (ADR-0028 п. 5, СУЩ-2.6). ERP не ответила — подсказок нет, поле работает
 * как обычное.
 */
export function RecipientField({
  id,
  value,
  onChange,
  onPick,
  describedBy,
  invalid,
}: {
  id: string;
  value: string;
  onChange: (name: string) => void;
  onPick: (addressee: EdsAddressee) => void;
  describedBy: string | undefined;
  invalid: boolean;
}) {
  const { t } = useTranslation("documents");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState<string | null>(null);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(value.trim());
    }, 250);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value]);
  const enabled = query.length >= MIN_QUERY;
  const found = useSearchEdsAddressees(
    { q: query },
    { query: { enabled, staleTime: 30_000, retry: false } },
  );
  const items = enabled ? (found.data?.items ?? []) : [];
  const exact = items.some(
    (item) => item.name.toLocaleLowerCase("ru") === query.toLocaleLowerCase("ru"),
  );
  const offerCreate = enabled && found.isSuccess && !exact;
  return (
    <>
      <AutoComplete
        id={id}
        value={value}
        maxLength={255}
        status={invalid ? "error" : undefined}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        placeholder={t("form.recipient.placeholder")}
        // выбор подсказки приходит и сюда — со значением id; название ставит onPick
        onChange={(next: string) => {
          if (next !== CREATE && !items.some((item) => item.id === next)) onChange(next);
        }}
        onSelect={(picked: string) => {
          if (picked === CREATE) {
            setCreating(query);
            return;
          }
          const addressee = items.find((item) => item.id === picked);
          if (addressee) onPick(addressee);
        }}
        options={[
          ...items.map((item) => ({
            value: item.id,
            label: (
              <span>
                {item.name}
                {item.inn ? (
                  <span className="pf-hint">
                    {" "}
                    · {t("form.recipient.innShort", { inn: item.inn })}
                  </span>
                ) : null}
              </span>
            ),
          })),
          ...(offerCreate
            ? [{ value: CREATE, label: t("form.recipient.create.option", { name: query }) }]
            : []),
        ]}
      />
      {creating !== null ? (
        <NewOrganization
          name={creating}
          onDone={(addressee) => {
            setCreating(null);
            onPick(addressee);
          }}
          onCancel={() => {
            setCreating(null);
          }}
        />
      ) : null}
    </>
  );
}

/** Новая организация-адресат: название, ИНН, адрес — в выезжающей панели поверх письма. */
function NewOrganization({
  name: initial,
  onDone,
  onCancel,
}: {
  name: string;
  onDone: (addressee: EdsAddressee) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("documents");
  const [name, setName] = useState(initial);
  const [inn, setInn] = useState("");
  const [address, setAddress] = useState("");
  const create = useCreateEdsAddressee({ mutation: { onSuccess: onDone } });
  const innValid = inn.trim() === "" || /^\d{9}$/.test(inn.trim());
  const error = create.error
    ? t(
        create.error instanceof ApiError && create.error.status === 409
          ? "form.recipient.create.exists"
          : "form.recipient.create.failed",
      )
    : null;
  return (
    <FormSheet
      title={t("form.recipient.create.title")}
      submitLabel={t("form.recipient.create.submit")}
      saving={create.isPending}
      submitDisabled={name.trim() === "" || !innValid}
      layer="drawer"
      dirty
      error={<ErrorNote message={error} />}
      onSubmit={() => {
        create.mutate({
          data: {
            name: name.trim(),
            inn: inn.trim() || null,
            legal_address: address.trim() || null,
          },
        });
      }}
      onCancel={onCancel}
    >
      <FormField id="eds-org-name" label={t("form.recipient.create.name")}>
        <Input
          id="eds-org-name"
          value={name}
          maxLength={255}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
      </FormField>
      <FormField
        id="eds-org-inn"
        label={t("form.recipient.create.inn")}
        hint={t("form.recipient.create.innHint")}
      >
        <Input
          id="eds-org-inn"
          value={inn}
          maxLength={9}
          inputMode="numeric"
          status={innValid ? undefined : "error"}
          aria-invalid={!innValid || undefined}
          aria-describedby="eds-org-inn-hint"
          onChange={(event) => {
            setInn(event.target.value);
          }}
        />
      </FormField>
      <FormField id="eds-org-address" label={t("form.recipient.create.address")}>
        <Input.TextArea
          id="eds-org-address"
          value={address}
          maxLength={500}
          autoSize={{ minRows: 2, maxRows: 4 }}
          onChange={(event) => {
            setAddress(event.target.value);
          }}
        />
      </FormField>
    </FormSheet>
  );
}

/**
 * «Кому — человек» (СУЩ-2.6): люди выбранной организации из её карточки. Выбор подставляет «Кому» (должность и имя) —
 * его можно поправить; пусто — письмо организации без конкретного человека.
 */
export function AddresseePerson({
  id,
  companyId,
  value,
  onPick,
}: {
  id: string;
  companyId: string;
  value: string;
  onPick: (person: EdsAddresseePeopleItemsItem | null) => void;
}) {
  const { t } = useTranslation("documents");
  const people = useListEdsAddresseePeople(companyId, {
    query: { enabled: companyId !== "", staleTime: 30_000, retry: false },
  });
  const items = companyId ? (people.data?.items ?? []) : [];
  return (
    <Select
      id={id}
      value={value || undefined}
      allowClear
      disabled={companyId === ""}
      loading={people.isFetching}
      placeholder={t("form.person.placeholder")}
      notFoundContent={t("form.person.empty")}
      aria-describedby={`${id}-hint`}
      options={items.map((person) => ({
        value: person.id,
        label: person.position ? `${person.name} · ${person.position}` : person.name,
      }))}
      onChange={(next: string | undefined) => {
        onPick(items.find((person) => person.id === next) ?? null);
      }}
    />
  );
}
