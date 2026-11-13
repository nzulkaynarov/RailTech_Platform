import { Alert, Button, Descriptions, Drawer, Input, Segmented, Skeleton } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { CounterpartyContacts } from "../../../shared/api/generated/model";
import {
  revealCounterpartyContacts,
  useListCounterpartyPeople,
  useListCrmLeads,
  useListEdsStaff,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { type DataColumn, DataTable } from "../../../shared/ui/DataTable/DataTable";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { SoonButton } from "../../../shared/ui/SoonButton";
import "./people.css";

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
  /** Контакт контрагента, у которого есть телефон или почта: открываются по нажатию с записью в журнал */
  revealId: string | null;
}

const STAFF_RULE = {
  anyOf: ["eds.inbox.register", "eds.inbox", "admin", "eds.signing.manage"],
  level: "full",
} as const;
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
  const [selected, setSelected] = useState<Person | null>(null);
  const title = t("modules:chats.sections.contacts");
  useDocumentTitle(title);

  const staff = useListEdsStaff({ query: { enabled: canSee(me, STAFF_RULE) } });
  const contacts = useListCounterpartyPeople({ page_size: CONTACTS_LIMIT });
  const leads = useListCrmLeads(
    { limit: LEADS_LIMIT },
    { query: { enabled: canSee(me, LEADS_RULE) } },
  );

  const people = useMemo<Person[]>(
    () => [
      ...(staff.data?.items ?? []).map((row) => ({
        key: `employee-${row.id}`,
        name: row.name,
        kind: "employees" as const,
        position: row.position,
        owner: null,
        company: null,
        revealId: null,
      })),
      ...(contacts.data?.items ?? []).map((row) => ({
        key: `contact-${row.id}`,
        name: row.name,
        kind: row.kind === "client" ? ("clients" as const) : ("partners" as const),
        position: row.position,
        owner: null,
        company: row.company.name,
        revealId: row.has_phone || row.has_email ? row.id : null,
      })),
      ...(leads.data?.items ?? []).map((row) => ({
        key: `lead-${row.lead}`,
        name: row.name,
        kind: "leads" as const,
        position: null,
        owner: row.assigned?.name ?? null,
        company: null,
        revealId: null,
      })),
    ],
    [staff.data, contacts.data, leads.data],
  );

  const needle = search.trim().toLocaleLowerCase();
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
  const reveal = (id: string) => {
    setRevealing(id);
    setRevealError(null);
    revealCounterpartyContacts(id)
      .then((value) => {
        setRevealed((prev) => ({ ...prev, [id]: value }));
      })
      .catch(() => {
        setRevealError(t("modules:chats.people.revealFailed"));
      })
      .finally(() => {
        setRevealing(null);
      });
  };
  const contactsOf = (person: Person, field: "phone" | "email" | "any") => {
    if (!person.revealId) return "—";
    const shown = revealed[person.revealId];
    if (!shown) {
      return (
        <Button
          size="small"
          loading={revealing === person.revealId}
          aria-label={t("modules:chats.people.showFor", { name: person.name })}
          onClick={() => {
            if (person.revealId) reveal(person.revealId);
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
            setSelected(person);
          }}
        >
          {person.name}
        </button>
      ),
    },
    {
      id: "position",
      header: t("modules:chats.people.columns.position"),
      width: null,
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
      width: null,
      cell: (row) => kindLabel(row.kind),
    },
    {
      id: "owner",
      header: t("modules:chats.people.columns.owner"),
      width: null,
      cell: (row) => row.owner ?? "—",
    },
    {
      id: "contacts",
      header: t("modules:chats.people.columns.contacts"),
      width: null,
      cell: (person) => contactsOf(person, "any"),
    },
  ];

  return (
    <div className="pf-people">
      <PageHeader title={title} />
      <div className="pf-people-controls">
        <Segmented
          aria-label={t("modules:chats.people.filter")}
          value={kind}
          options={KINDS.map((value) => ({ value, label: kindLabel(value) }))}
          onChange={setKind}
        />
        <Input.Search
          allowClear
          aria-label={t("modules:chats.people.search")}
          placeholder={t("modules:chats.people.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
          style={{ maxWidth: 280 }}
        />
      </div>
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : rows.length === 0 ? (
        <p className="pf-hint">{t("modules:chats.people.noData")}</p>
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
      <Drawer
        open={selected !== null}
        title={selected?.name}
        width={400}
        onClose={() => {
          setSelected(null);
        }}
      >
        {selected ? (
          <div className="pf-people-card">
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
                {
                  key: "company",
                  label: t("modules:chats.people.columns.company"),
                  children: selected.company ?? "—",
                },
                {
                  key: "kind",
                  label: t("modules:chats.people.columns.kind"),
                  children: kindLabel(selected.kind),
                },
                {
                  key: "phone",
                  label: t("modules:chats.people.phone"),
                  children: contactsOf(selected, "phone"),
                },
                {
                  key: "email",
                  label: t("modules:chats.people.email"),
                  children: contactsOf(selected, "email"),
                },
              ]}
            />
            <div className="pf-people-actions">
              <SoonButton>{t("modules:chats.people.write")}</SoonButton>
              <SoonButton>{t("modules:chats.people.call")}</SoonButton>
            </div>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
