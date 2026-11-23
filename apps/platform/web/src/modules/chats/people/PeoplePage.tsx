import { Alert, Button, Card, Descriptions, Input, Segmented } from "antd";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { CounterpartyContacts } from "../../../shared/api/generated/model";
import {
  revealCounterpartyContacts,
  revealStaffContacts,
  useListCounterpartyPeople,
  useListCrmLeads,
  useListStaffDirectory,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { DataBlock, ListSkeleton } from "../../../shared/ui/DataBlock";
import { type DataColumn, DataTable } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PersonCell } from "../../../shared/ui/EntityCell";
import { PageHeader } from "../../../shared/ui/PageHeader";
import "./people.css";
import { FilterBar, FilterField } from "../../../shared/ui/FilterBar";
import { Sheet } from "../../../shared/ui/Sheet";
import { useParamChanger } from "../../crm/common/params";

/** Ширины по типу столбца (platform-frontend.md §4.2): имя и компания делят остаток, короткие значения — фиксированные. */
const COLS = { position: 180, kind: 150, owner: 170, contacts: 170 };

const KINDS = ["all", "employees", "clients", "partners", "leads"] as const;
type Kind = (typeof KINDS)[number];

interface Person {
  key: string;
  name: string;
  kind: Exclude<Kind, "all">;
  position: string | null;
  owner: string | null;
  /** Компания контрагента (люди клиентов и партнёров) */
  company: string | null;
  /** Сотрудник, у которого есть телефон или почта, либо контакт контрагента: открываются по нажатию с записью в журнал */
  revealId: string | null;
  /** Откуда контакты: профиль сотрудника в CRM или ERP */
  revealFrom: "staff" | "counterparty" | null;
  /** Роли Платформы словами (только сотрудники) */
  roles: string[];
  photoUrl: string | null;
}

const LEADS_RULE = { anyOf: ["crm.leads", "crm.leads.triage"] } as const;
const LEADS_LIMIT = 100;
/** Люди клиентов и партнёров (FR-11): первые 200 по имени; поиск по остальным — на сервере, когда понадобится */
const CONTACTS_LIMIT = 200;

/** Органайзер · Люди: единый список поверх источников, открытых роли. */
export function PeoplePage() {
  const { t } = useTranslation(["modules"]);
  const { me } = useAuth();
  const [kind, setKind] = useState<Kind>("all");
  const [search, setSearch] = useState("");
  const { mobile } = useViewport();
  const [params] = useSearchParams();
  const change = useParamChanger();
  const selectedKey = params.get("person");
  const title = t("modules:chats.sections.contacts");
  useDocumentTitle(title);

  // Решение 10.11: имя, должность и роли сотрудников видят все, у кого есть «Люди»; контакты — по нажатию.
  const staff = useListStaffDirectory();
  const contacts = useListCounterpartyPeople({ page_size: CONTACTS_LIMIT });
  const leads = useListCrmLeads(
    { limit: LEADS_LIMIT },
    { query: { enabled: canSee(me, LEADS_RULE) } },
  );

  const people = useMemo<Person[]>(
    () => [
      ...(staff.data?.items ?? [])
        .filter((row) => row.active)
        .map((row) => ({
          key: `employee-${row.id}`,
          name: row.name,
          kind: "employees" as const,
          position: row.position,
          owner: null,
          company: null,
          revealId: row.id,
          revealFrom: "staff" as const,
          roles: row.roles ?? [],
          photoUrl: row.avatar_url,
        })),
      ...(contacts.data?.items ?? []).map((row) => ({
        key: `contact-${row.id}`,
        name: row.name,
        kind: row.kind === "client" ? ("clients" as const) : ("partners" as const),
        position: row.position,
        owner: null,
        company: row.company.name,
        revealId: row.has_phone || row.has_email ? row.id : null,
        revealFrom: "counterparty" as const,
        roles: [],
        photoUrl: null,
      })),
      ...(leads.data?.items ?? []).map((row) => ({
        key: `lead-${row.lead}`,
        name: row.name,
        kind: "leads" as const,
        position: null,
        owner: row.assigned?.name ?? null,
        company: null,
        revealId: null,
        revealFrom: null,
        roles: [],
        photoUrl: null,
      })),
    ],
    [staff.data, contacts.data, leads.data],
  );

  const needle = search.trim().toLocaleLowerCase();
  const selected = people.find((person) => person.key === selectedKey) ?? null;
  const open = (person: Person) => {
    change({ person: person.key, panel: mobile ? null : "open", tab: mobile ? null : "card" });
  };
  const close = () => {
    change({ person: null, panel: null, tab: null });
  };
  const rows = people.filter(
    (person) =>
      (kind === "all" || person.kind === kind) &&
      (needle === "" ||
        person.name.toLocaleLowerCase().includes(needle) ||
        (person.company ?? "").toLocaleLowerCase().includes(needle)),
  );

  const kindLabel = (value: Kind) => t(`modules:chats.people.kinds.${value}`);
  // Телефон и почта людей контрагентов — по нажатию «Показать», показ пишет BFF в журнал (NAVIGATION «Люди»).
  const [revealed, setRevealed] = useState<Record<string, CounterpartyContacts>>({});
  const [revealing, setRevealing] = useState<string | null>(null);
  const [revealError, setRevealError] = useState<string | null>(null);
  const reveal = (person: Person) => {
    if (!person.revealId) return;
    setRevealing(person.key);
    setRevealError(null);
    const request =
      person.revealFrom === "staff"
        ? revealStaffContacts(person.revealId)
        : revealCounterpartyContacts(person.revealId);
    request
      .then((value) => {
        setRevealed((prev) => ({ ...prev, [person.key]: value }));
      })
      .catch(() => {
        setRevealError(t("modules:chats.people.revealFailed"));
      })
      .finally(() => {
        setRevealing(null);
      });
  };
  const contactsOf = (person: Person, field: "phone" | "email" | "any", inCard = false) => {
    if (!person.revealId) return "—";
    const shown = revealed[person.key];
    if (!shown) {
      // В карточке одна кнопка «Показать контакты» на оба поля; до нажатия значения скрыты
      if (inCard) return "•••";
      return (
        <Button
          size="small"
          loading={revealing === person.key}
          aria-label={t("modules:chats.people.showFor", { name: person.name })}
          onClick={() => {
            reveal(person);
          }}
        >
          {t("modules:chats.people.show")}
        </Button>
      );
    }
    const phone = shown.phone ? <a href={`tel:${shown.phone}`}>{shown.phone}</a> : null;
    const email = shown.email ? <a href={`mailto:${shown.email}`}>{shown.email}</a> : null;
    if (field === "phone") return phone ?? "—";
    if (field === "email") return email ?? "—";
    return phone ?? email ?? "—";
  };
  const loading = staff.isLoading || contacts.isLoading || leads.isLoading;
  const columns: DataColumn<Person>[] = [
    {
      id: "name",
      header: t("modules:chats.people.columns.name"),
      width: null,
      cell: (person) => (
        <button
          type="button"
          className="pf-people-name"
          onClick={() => {
            open(person);
          }}
        >
          {person.name}
        </button>
      ),
    },
    {
      id: "position",
      header: t("modules:chats.people.columns.position"),
      width: COLS.position,
      cell: (row) => row.position ?? "—",
    },
    {
      id: "company",
      header: t("modules:chats.people.columns.company"),
      width: null,
      cell: (row) => row.company ?? "—",
    },
    {
      id: "kind",
      header: t("modules:chats.people.columns.kind"),
      width: COLS.kind,
      cell: (row) => kindLabel(row.kind),
    },
    {
      id: "owner",
      header: t("modules:chats.people.columns.owner"),
      width: COLS.owner,
      cell: (row) => row.owner ?? "—",
    },
    {
      id: "contacts",
      header: t("modules:chats.people.columns.contacts"),
      width: COLS.contacts,
      cell: (person) => contactsOf(person, "any"),
    },
  ];

  return (
    <div className="pf-people">
      <PageHeader title={title} />
      <FilterBar tools>
        <Segmented
          aria-label={t("modules:chats.people.filter")}
          value={kind}
          options={KINDS.map((value) => ({ value, label: kindLabel(value) }))}
          onChange={setKind}
        />
        <FilterField id="pf-people-q" label={t("modules:chats.people.search")} grow>
          <Input.Search
            id="pf-people-q"
            allowClear
            placeholder={t("modules:chats.people.search")}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
            }}
          />
        </FilterField>
      </FilterBar>
      <Card styles={{ body: { padding: 0 } }}>
        <DataBlock>
          {loading ? (
            <ListSkeleton rows={8} />
          ) : rows.length === 0 ? (
            <EmptyState
              title={t("modules:chats.people.empty.title")}
              text={t("modules:chats.people.empty.text")}
            />
          ) : (
            <DataTable<Person>
              tableId="chats.people"
              caption={title}
              scrollLabel={title}
              columns={columns}
              rows={rows}
              rowKey={(row) => row.key}
              pageSize={20}
            />
          )}
        </DataBlock>
      </Card>
      {selected ? (
        <Sheet label={selected.name} onClose={close}>
          <div className="pf-people-card">
            <PersonCell
              name={selected.name}
              caption={selected.position}
              photoUrl={selected.photoUrl}
              size={40}
              title={<h2 className="pf-people-card__title">{selected.name}</h2>}
            />
            {revealError ? (
              <Alert type="error" showIcon role="alert" message={revealError} />
            ) : null}
            <Descriptions
              column={1}
              items={[
                {
                  key: "position",
                  label: t("modules:chats.people.columns.position"),
                  children: selected.position ?? "—",
                },
                ...(selected.kind === "employees"
                  ? [
                      {
                        key: "roles",
                        label: t("modules:chats.people.roles"),
                        children: selected.roles.length > 0 ? selected.roles.join(", ") : "—",
                      },
                    ]
                  : [
                      {
                        key: "company",
                        label: t("modules:chats.people.columns.company"),
                        children: selected.company ?? "—",
                      },
                    ]),
                {
                  key: "kind",
                  label: t("modules:chats.people.columns.kind"),
                  children: kindLabel(selected.kind),
                },
                {
                  key: "phone",
                  label: t("modules:chats.people.phone"),
                  children: contactsOf(selected, "phone", true),
                },
                {
                  key: "email",
                  label: t("modules:chats.people.email"),
                  children: contactsOf(selected, "email", true),
                },
              ]}
            />
            <div className="pf-people-card__actions">
              {selected.revealId && !revealed[selected.key] ? (
                <Button
                  type="primary"
                  loading={revealing === selected.key}
                  onClick={() => {
                    reveal(selected);
                  }}
                >
                  {t("modules:chats.people.reveal")}
                </Button>
              ) : null}
              <Button onClick={close}>{t("modules:chats.people.close")}</Button>
            </div>
          </div>
        </Sheet>
      ) : null}
    </div>
  );
}
