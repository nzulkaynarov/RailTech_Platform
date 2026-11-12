import { Descriptions, Drawer, Input, Segmented, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import {
  useListCounterpartyPeople,
  useListCrmLeads,
  useListEdsStaff,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
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
  phone: string | null;
  email: string | null;
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
        phone: null,
        email: null,
      })),
      ...(contacts.data?.items ?? []).map((row) => ({
        key: `contact-${row.id}`,
        name: row.name,
        kind: row.kind === "client" ? ("clients" as const) : ("partners" as const),
        position: row.position,
        owner: null,
        company: row.company.name,
        phone: row.phone,
        email: row.email,
      })),
      ...(leads.data?.items ?? []).map((row) => ({
        key: `lead-${row.lead}`,
        name: row.name,
        kind: "leads" as const,
        position: null,
        owner: row.assigned?.name ?? null,
        company: null,
        phone: null,
        email: null,
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
  const columns: ColumnsType<Person> = [
    {
      title: t("modules:chats.people.columns.name"),
      dataIndex: "name",
      render: (_, person) => (
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
      title: t("modules:chats.people.columns.position"),
      dataIndex: "position",
      render: (value: string | null) => value ?? "—",
    },
    {
      title: t("modules:chats.people.columns.company"),
      dataIndex: "company",
      render: (value: string | null) => value ?? "—",
    },
    {
      title: t("modules:chats.people.columns.kind"),
      dataIndex: "kind",
      render: (value: Kind) => kindLabel(value),
    },
    {
      title: t("modules:chats.people.columns.owner"),
      dataIndex: "owner",
      render: (value: string | null) => value ?? "—",
    },
    {
      title: t("modules:chats.people.columns.contacts"),
      key: "contacts",
      render: (_, person) => person.phone ?? person.email ?? "—",
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
      <Table<Person>
        rowKey="key"
        columns={columns}
        dataSource={rows}
        loading={staff.isFetching || contacts.isFetching || leads.isFetching}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        scroll={{ x: "max-content" }}
        locale={{ emptyText: t("modules:chats.people.noData") }}
      />
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
                  children: selected.phone ? (
                    <a href={`tel:${selected.phone}`}>{selected.phone}</a>
                  ) : (
                    "—"
                  ),
                },
                {
                  key: "email",
                  label: t("modules:chats.people.email"),
                  children: selected.email ? (
                    <a href={`mailto:${selected.email}`}>{selected.email}</a>
                  ) : (
                    "—"
                  ),
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
