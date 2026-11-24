import { Alert, Button, Card, Descriptions, Input, Segmented, Switch } from "antd";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { PersonRef } from "../../../shared/api/generated/model";
import {
  revealCounterpartyContacts,
  revealLeadContacts,
  revealStaffContacts,
  useListCounterpartyPeople,
  useListPeopleLeads,
  useListStaffDirectory,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { DataBlock, ListSkeleton } from "../../../shared/ui/DataBlock";
import { type DataColumn, DataTable } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { CompanyCell, PersonCell } from "../../../shared/ui/EntityCell";
import { MailIcon, PhoneIcon, SendIcon } from "../../../shared/ui/lucide";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { ROW_ACTIONS_WIDTH, RowActions } from "../../../shared/ui/RowActions";
import "./people.css";
import { FilterBar, FilterField } from "../../../shared/ui/FilterBar";
import { Sheet } from "../../../shared/ui/Sheet";
import { useParamChanger } from "../../crm/common/params";
import { channelLabel } from "../../crm/messages/labels";
import { PersonRefCell } from "../../PersonRefCell";

/** Ширины по типу столбца (platform-frontend.md §4.2): имя и компания делят остаток, короткие значения — фиксированные. */
const COLS = { position: 180, kind: 150, owner: 170, contacts: 170 };

const KINDS = ["all", "employees", "clients", "partners", "leads"] as const;
type Kind = (typeof KINDS)[number];

/** Лид в «Людях» (PL-1): номер для ссылки, канал, язык, суть запроса и что из контактов есть */
interface LeadInfo {
  number: string;
  channel: string;
  language: string;
  need: string | null;
  closed: boolean;
  has: { phone: boolean; email: boolean; telegram: boolean };
}

/** Раскрытые по нажатию контакты; Telegram — только у лидов */
interface Revealed {
  phone: string | null;
  email: string | null;
  telegram?: string | null;
}

interface Person {
  key: string;
  name: string;
  kind: Exclude<Kind, "all">;
  position: string | null;
  /** Ответственный за лид: сотрудник со справочником (фото или инициалы) */
  owner: Pick<PersonRef, "id" | "name"> | null;
  /** Компания контрагента (люди клиентов и партнёров): название и логотип, ЕД-3 */
  company: { name: string; logoUrl: string | null } | null;
  /** Сотрудник, у которого есть телефон или почта, либо контакт контрагента: открываются по нажатию с записью в журнал */
  revealId: string | null;
  /** Откуда контакты: профиль сотрудника в CRM, контакт ERP или сам лид CRM */
  revealFrom: "staff" | "counterparty" | "lead" | null;
  /** Только лиды: то, что CRM знает о лиде; значения контактов — по нажатию */
  lead: LeadInfo | null;
  /** Роли Платформы словами (только сотрудники) */
  roles: string[];
  photoUrl: string | null;
}

const LEADS_RULE = { anyOf: ["crm.leads", "crm.leads.triage"] } as const;
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
  // Лиды: ещё не клиенты; проигранные — только по переключателю «Показать закрытые»
  const [closed, setClosed] = useState(false);
  const leads = useListPeopleLeads({ closed }, { query: { enabled: canSee(me, LEADS_RULE) } });
  const navigate = useNavigate();

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
          lead: null,
          roles: row.roles ?? [],
          photoUrl: row.avatar_url,
        })),
      ...(contacts.data?.items ?? []).map((row) => ({
        key: `contact-${row.id}`,
        name: row.name,
        kind: row.kind === "client" ? ("clients" as const) : ("partners" as const),
        position: row.position,
        owner: null,
        company: { name: row.company.name, logoUrl: row.company_logo_url ?? null },
        revealId: row.has_phone || row.has_email ? row.id : null,
        revealFrom: "counterparty" as const,
        lead: null,
        roles: [],
        photoUrl: row.photo_url ?? null,
      })),
      ...(leads.data?.items ?? []).map((row) => ({
        key: `lead-${row.lead}`,
        name: row.name,
        kind: "leads" as const,
        position: null,
        owner: row.assigned,
        company: row.company ? { name: row.company, logoUrl: null } : null,
        revealId: row.has_phone || row.has_email || row.has_telegram ? row.lead : null,
        revealFrom: "lead" as const,
        lead: {
          number: row.lead,
          channel: row.channel,
          language: row.language,
          need: row.need,
          closed: row.status === "lost",
          has: { phone: row.has_phone, email: row.has_email, telegram: row.has_telegram },
        },
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
        (person.company?.name ?? "").toLocaleLowerCase().includes(needle)),
  );

  const kindLabel = (value: Kind) => t(`modules:chats.people.kinds.${value}`);
  // Телефон и почта людей контрагентов — по нажатию «Показать», показ пишет BFF в журнал (NAVIGATION «Люди»).
  const [revealed, setRevealed] = useState<Record<string, Revealed>>({});
  const [revealing, setRevealing] = useState<string | null>(null);
  const [revealError, setRevealError] = useState<string | null>(null);
  const reveal = (person: Person) => {
    if (!person.revealId) return;
    setRevealing(person.key);
    setRevealError(null);
    const request: Promise<Revealed> =
      person.revealFrom === "staff"
        ? revealStaffContacts(person.revealId)
        : person.revealFrom === "lead"
          ? revealLeadContacts(person.revealId)
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
  const contactsOf = (person: Person, field: "phone" | "email" | "telegram" | "any") => {
    if (!person.revealId) return "—";
    const shown = revealed[person.key];
    if (!shown) {
      // Значения скрыты до показа: в карточке — кнопка «Показать контакты», в таблице — пункт меню строки
      if (person.lead && field === "any") return <LeadContactIcons has={person.lead.has} />;
      if (person.lead && !person.lead.has[field === "telegram" ? "telegram" : field]) return "—";
      return "•••";
    }
    const phone = shown.phone ? <a href={`tel:${shown.phone}`}>{shown.phone}</a> : null;
    const email = shown.email ? <a href={`mailto:${shown.email}`}>{shown.email}</a> : null;
    if (field === "phone") return phone ?? "—";
    if (field === "email") return email ?? "—";
    if (field === "telegram") return shown.telegram ?? "—";
    return phone ?? email ?? shown.telegram ?? "—";
  };
  const loading = staff.isLoading || contacts.isLoading || leads.isLoading;
  const columns: DataColumn<Person>[] = [
    {
      id: "name",
      header: t("modules:chats.people.columns.name"),
      width: null,
      cell: (person) => (
        <PersonCell
          name={person.name}
          photoUrl={person.photoUrl}
          size={32}
          title={
            <button
              type="button"
              className="pf-people-name"
              onClick={() => {
                open(person);
              }}
            >
              {person.name}
            </button>
          }
        />
      ),
    },
    {
      id: "position",
      header: t("modules:chats.people.columns.position"),
      width: COLS.position,
      priority: 2,
      truncate: true,
      cell: (row) => row.position ?? "—",
    },
    {
      id: "company",
      header: t("modules:chats.people.columns.company"),
      width: null,
      truncate: true,
      cell: (row) =>
        row.company ? <CompanyCell name={row.company.name} logoUrl={row.company.logoUrl} /> : "—",
    },
    {
      id: "kind",
      header: t("modules:chats.people.columns.kind"),
      width: COLS.kind,
      cell: (row) =>
        row.lead?.closed
          ? `${kindLabel(row.kind)} · ${t("modules:chats.people.closedLead")}`
          : kindLabel(row.kind),
    },
    {
      id: "owner",
      header: t("modules:chats.people.columns.owner"),
      width: COLS.owner,
      priority: 3,
      truncate: true,
      cell: (row) => (row.owner ? <PersonRefCell person={row.owner} caption={null} /> : "—"),
    },
    {
      id: "contacts",
      header: t("modules:chats.people.columns.contacts"),
      width: COLS.contacts,
      cell: (person) => contactsOf(person, "any"),
    },
    {
      id: "actions",
      header: t("modules:chats.people.columns.actions"),
      headerHidden: true,
      width: ROW_ACTIONS_WIDTH,
      cell: (person) =>
        person.revealId && !revealed[person.key] ? (
          <RowActions
            name={person.name}
            items={[
              {
                key: "reveal",
                label: t("modules:chats.people.reveal"),
                disabled: revealing === person.key,
                onClick: () => {
                  reveal(person);
                },
              },
            ]}
          />
        ) : null,
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
        {canSee(me, LEADS_RULE) && (kind === "all" || kind === "leads") ? (
          <label className="pf-people-closed">
            <Switch size="small" checked={closed} onChange={setClosed} />
            <span>{t("modules:chats.people.showClosed")}</span>
          </label>
        ) : null}
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
                // у лида должности нет: CRM её не собирает
                ...(selected.lead
                  ? []
                  : [
                      {
                        key: "position",
                        label: t("modules:chats.people.columns.position"),
                        children: selected.position ?? "—",
                      },
                    ]),
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
                        children: selected.company ? (
                          <CompanyCell
                            name={selected.company.name}
                            logoUrl={selected.company.logoUrl}
                          />
                        ) : (
                          "—"
                        ),
                      },
                    ]),
                {
                  key: "kind",
                  label: t("modules:chats.people.columns.kind"),
                  children: kindLabel(selected.kind),
                },
                ...(selected.lead
                  ? [
                      {
                        key: "channel",
                        label: t("modules:chats.people.channel"),
                        children: channelLabel(t, selected.lead.channel),
                      },
                      {
                        key: "language",
                        label: t("modules:chats.people.language"),
                        children: t(`modules:chats.people.languages.${selected.lead.language}`, {
                          defaultValue: selected.lead.language,
                        }),
                      },
                      {
                        key: "need",
                        label: t("modules:chats.people.need"),
                        children: selected.lead.need ?? "—",
                      },
                    ]
                  : []),
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
                ...(selected.lead
                  ? [
                      {
                        key: "telegram",
                        label: t("modules:chats.people.telegram"),
                        children: contactsOf(selected, "telegram"),
                      },
                    ]
                  : []),
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
              {selected.lead ? (
                <Button
                  onClick={() => {
                    void navigate(`/crm/leads/${selected.lead?.number ?? ""}`);
                  }}
                >
                  {t("modules:chats.people.openLead", { number: selected.lead.number })}
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

/** Что из контактов у лида есть: значки без значений, значения открывает «Показать контакты» */
function LeadContactIcons({ has }: { has: LeadInfo["has"] }) {
  const { t } = useTranslation(["modules"]);
  const items = [
    { on: has.phone, icon: <PhoneIcon />, label: t("modules:chats.people.phone") },
    { on: has.email, icon: <MailIcon />, label: t("modules:chats.people.email") },
    { on: has.telegram, icon: <SendIcon />, label: t("modules:chats.people.telegram") },
  ].filter((item) => item.on);
  return (
    <span className="pf-people-has">
      {items.map((item) => (
        <span key={item.label} role="img" aria-label={item.label} title={item.label}>
          {item.icon}
        </span>
      ))}
    </span>
  );
}
