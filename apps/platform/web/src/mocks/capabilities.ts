import { HttpResponse, http } from "msw";

import type {
  CapabilityAuthority,
  CapabilityGroup,
  CapabilityLevel,
  CapabilityMatrix,
  CapabilityPerson,
  CapabilityRow,
  CapabilityText,
  CapabilityWarning,
  CapabilityZone,
  EmployeeCapabilities,
  RoleRef,
} from "../shared/api/generated/model";
import { companyToday } from "../shared/lib/dates";
import catalog from "./fixtures/capabilities.generated.json";
import { type MockEmployee, readEmployees, toEmployee } from "./fixtures/employees";
import { type MockRole, readRoles, roleRefOf, rolesOf } from "./fixtures/roles";
import { buildMe, currentActor, readSession } from "./mockSession";
import { readSigningAuthorities } from "./signing";
import { readZones } from "./zones";

/**
 * Моки «Что может человек» (ДОСТ-1): каталог и включённость действий по ролям каталога берутся из настоящего расчёта BFF
 * (`gen_capability_mocks.py` → `fixtures/capabilities.generated.json`), роли сотрудника складываются так же, как BFF складывает
 * действия: действие включено, если включено хотя бы в одной роли. Созданная в интерфейсе роль без кода считается по условиям
 * разделов (коды бэкендов в моке не пересчитываются). Сотрудники, подписи и зоны — из моков экранов, вымышленные.
 */
type Level = "view" | "work" | "decide";
interface Action {
  key: string;
  text: CapabilityText;
  gates: string[];
  fields?: string[];
  erp_superuser?: boolean;
}
interface Cap {
  key: string;
  group: string;
  name: CapabilityText;
  levels: { level: Level; actions: Action[] }[];
}
const CATALOG = catalog as unknown as {
  free_for_all: CapabilityText;
  groups: { key: string; step: CapabilityText; name: CapabilityText }[];
  capabilities: Cap[];
  roles: Record<string, Record<string, Record<string, boolean>>>;
};
const ORDER: readonly CapabilityLevel[] = ["none", "view", "work", "decide"];

function gateOk(access: Partial<Record<string, string>>, gate: string): boolean {
  return gate.split("|").some((alt) => {
    const [resource = "", level = ""] = alt.split(":");
    const held = access[resource];
    return held !== undefined && (level === "read" || held === "full");
  });
}

function isPreset(role: MockRole): boolean {
  const code = role.code?.replace(/^tpl:/, "");
  return code !== undefined && code in CATALOG.roles;
}

function onFor(roles: readonly MockRole[]): Record<string, Record<string, boolean>> {
  const custom = roles.filter((r) => !isPreset(r));
  const access: Record<string, string> = {};
  for (const role of custom)
    for (const [key, level] of Object.entries(role.access))
      if (level && (access[key] !== "full" || level === "full")) access[key] = level;
  const fields = new Set(custom.flatMap((r) => r.restricted_fields as string[]));
  const out: Record<string, Record<string, boolean>> = {};
  for (const cap of CATALOG.capabilities) {
    const on: Record<string, boolean> = {};
    for (const level of cap.levels)
      for (const action of level.actions) {
        const preset = roles.some((r) => {
          const code = r.code?.replace(/^tpl:/, "") ?? "";
          return CATALOG.roles[code]?.[cap.key]?.[action.key] === true;
        });
        const byGates =
          custom.length > 0 &&
          !action.erp_superuser &&
          action.gates.every((g) => gateOk(access, g)) &&
          (action.fields ?? []).every((f) => fields.has(f));
        on[action.key] = preset || byGates;
      }
    out[cap.key] = on;
  }
  return out;
}

interface State {
  level: CapabilityLevel;
  partial: boolean;
  on: Record<string, boolean>;
}

function evaluate(roles: readonly MockRole[]): Record<string, State> {
  const on = onFor(roles);
  const out: Record<string, State> = {};
  for (const cap of CATALOG.capabilities) {
    const flags = on[cap.key] ?? {};
    let top: CapabilityLevel = "none";
    for (const level of cap.levels)
      if (
        level.actions.some((a) => flags[a.key]) &&
        ORDER.indexOf(level.level) > ORDER.indexOf(top)
      )
        top = level.level;
    const partial =
      top !== "none" &&
      cap.levels.some(
        (level) =>
          ORDER.indexOf(level.level) <= ORDER.indexOf(top) &&
          level.actions.some((a) => !flags[a.key]),
      );
    out[cap.key] = { level: top, partial, on: flags };
  }
  return out;
}

const personOf = (e: {
  id: string;
  name: string;
  initials: string;
  position?: string;
}): CapabilityPerson => ({
  id: e.id,
  name: e.name,
  initials: e.initials,
  ...(e.position ? { position: e.position } : {}),
});

function rolesOfEmployee(e: MockEmployee): MockRole[] {
  return rolesOf(e.role_ids, readRoles());
}

function joinTexts(parts: CapabilityText[][]): CapabilityText | undefined {
  const flat = parts.flat();
  if (flat.length === 0) return undefined;
  const lang = (key: keyof CapabilityText) => flat.map((p) => p[key]).join(", ");
  return { ru: lang("ru"), uz: lang("uz"), en: lang("en") };
}

function lower(text: CapabilityText): CapabilityText {
  const f = (s: string) => s.slice(0, 1).toLowerCase() + s.slice(1);
  return { ru: f(text.ru), uz: f(text.uz), en: f(text.en) };
}

function summary(states: Record<string, State>) {
  const does: CapabilityText[] = [];
  const decides: CapabilityText[] = [];
  const lacks: CapabilityText[] = [];
  for (const cap of CATALOG.capabilities) {
    const state = states[cap.key];
    if (!state) continue;
    if ((state.level === "work" || state.level === "decide") && cap.key !== "exceptional")
      does.push(lower(cap.name));
    if (state.level === "decide")
      for (const level of cap.levels)
        if (level.level === "decide")
          for (const action of level.actions) if (state.on[action.key]) decides.push(action.text);
    if (state.level === "none") lacks.push(lower(cap.name));
  }
  const shown = lacks.slice(0, 6);
  const more = lacks.length - shown.length;
  const lacksText = joinTexts([shown]);
  return {
    ...(joinTexts([does]) ? { does: joinTexts([does]) as CapabilityText } : {}),
    ...(joinTexts([decides]) ? { decides: joinTexts([decides]) as CapabilityText } : {}),
    ...(lacksText
      ? {
          lacks:
            more > 0
              ? {
                  ru: `${lacksText.ru} и ещё ${String(more)}`,
                  uz: `${lacksText.uz} va yana ${String(more)} ta`,
                  en: `${lacksText.en} and ${String(more)} more`,
                }
              : lacksText,
        }
      : {}),
  };
}

function authoritiesOf(): Map<string, CapabilityAuthority[]> {
  const today = companyToday();
  const out = new Map<string, CapabilityAuthority[]>();
  for (const item of readSigningAuthorities()) {
    if (item.revoked || (item.valid_to && item.valid_to < today) || item.valid_from > today)
      continue;
    const list = out.get(item.holderId) ?? [];
    list.push({
      id: item.id,
      kinds: item.kinds,
      ...(item.limit ? { limit: item.limit } : {}),
      basis: item.basis,
      ...(item.basis_number ? { basis_number: item.basis_number } : {}),
      ...(item.valid_to ? { valid_to: item.valid_to } : {}),
    });
    out.set(item.holderId, list);
  }
  return out;
}

function zonesOf(): Map<string, CapabilityZone[]> {
  const out = new Map<string, CapabilityZone[]>();
  for (const zone of readZones()) {
    if (!zone.active) continue;
    for (const [role, id] of [
      ["responsible", zone.responsibleId],
      ["deputy", zone.deputyId],
      ["curator", zone.curatorId],
    ] as const) {
      if (!id) continue;
      const list = out.get(id) ?? [];
      list.push({
        id: zone.id,
        code: zone.code,
        name: zone.name,
        role,
        ...(zone.valid_to ? { valid_to: zone.valid_to } : {}),
      });
      out.set(id, list);
    }
  }
  return out;
}

interface Row {
  employee: MockEmployee;
  roles: MockRole[];
  states: Record<string, State>;
}

function company(): Row[] {
  return readEmployees()
    .filter((e) => e.status !== "disabled" && e.role_ids.length > 0 && !e.is_service)
    .map((employee) => {
      const roles = rolesOfEmployee(employee);
      return { employee, roles, states: evaluate(roles) };
    })
    .sort((a, b) => a.employee.name.localeCompare(b.employee.name, "ru"));
}

function deputyOf(employee: MockEmployee): Pick<EmployeeCapabilities, "deputy"> {
  const deputy = toEmployee(employee).deputy;
  return deputy ? { deputy } : {};
}

function warningsOf(rows: readonly Row[]) {
  const found: CapabilityWarning[] = [];
  for (const cap of CATALOG.capabilities) {
    if (cap.key === "exceptional" || !cap.levels.some((l) => l.level === "decide")) continue;
    const holders = rows.filter((r) => r.states[cap.key]?.level === "decide");
    if (holders.length === 0) found.push({ code: "nobody_decides", capability: cap.key });
    else if (holders.length === 1 && holders[0]) {
      const holder = holders[0].employee;
      found.push({
        code: "only_decider",
        capability: cap.key,
        person: personOf(holder),
        has_deputy: Boolean(
          toEmployee(holder).deputy && (toEmployee(holder).deputy?.date_to ?? "") >= companyToday(),
        ),
      });
    }
  }
  return found;
}

function guard(): Response | null {
  const session = readSession();
  const me = session ? buildMe(session) : undefined;
  if (!me)
    return HttpResponse.json(
      { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
      { status: 401 },
    );
  return null;
}

function forbidden(): Response {
  return HttpResponse.json(
    { code: "FORBIDDEN", message: "Раздел или действие не положены вашей роли.", source: "bff" },
    { status: 403 },
  );
}

function adminRead(): Response | null {
  const denied = guard();
  if (denied) return denied;
  const session = readSession();
  const me = session ? buildMe(session) : undefined;
  return me?.resources["admin"] ? null : forbidden();
}

function cardOf(
  person: CapabilityPerson,
  roles: MockRole[],
  everyone: readonly Row[] | null,
  deputy: EmployeeCapabilities["deputy"],
  known: { signing: boolean; zones: boolean },
): EmployeeCapabilities {
  const states = evaluate(roles);
  const signing = authoritiesOf();
  const zones = zonesOf();
  const groups: CapabilityGroup[] = CATALOG.groups.map((group) => ({
    key: group.key,
    step: group.step,
    name: group.name,
    rows: CATALOG.capabilities
      .filter((cap) => cap.group === group.key)
      .map((cap): CapabilityRow => {
        const state = states[cap.key] as State;
        const others =
          everyone && state.level !== "none"
            ? everyone.filter(
                (r) =>
                  r.employee.id !== person.id &&
                  ORDER.indexOf(r.states[cap.key]?.level ?? "none") >= ORDER.indexOf(state.level),
              )
            : [];
        return {
          key: cap.key,
          group: cap.group,
          name: cap.name,
          level: state.level,
          partial: state.partial,
          levels: cap.levels.map((level) => ({
            level: level.level,
            actions: level.actions.map((a) => ({
              key: a.key,
              text: a.text,
              on: state.on[a.key] === true,
              gates: a.gates,
            })),
          })),
          from_roles: roles
            .filter((r) => {
              const single = evaluate([r])[cap.key];
              return single !== undefined && single.level !== "none";
            })
            .map((r): RoleRef => roleRefOf(r)),
          others: others.slice(0, 5).map((r) => personOf(r.employee)),
          others_total: others.length,
        };
      }),
  }));
  const text = summary(states);
  return {
    employee: person,
    roles: roles.map(roleRefOf),
    summary: text,
    groups,
    signing_known: known.signing,
    signing: known.signing ? (signing.get(person.id) ?? []) : [],
    zones_known: known.zones,
    zones: known.zones ? (zones.get(person.id) ?? []) : [],
    ...(deputy ? { deputy } : {}),
    warnings: everyone ? warningsOf(everyone).filter((w) => w.person?.id === person.id) : [],
    free_for_all: CATALOG.free_for_all,
  };
}

export const capabilitiesHandlers = [
  http.get("*/admin/capabilities", () => {
    const denied = adminRead();
    if (denied) return denied;
    const rows = company();
    const signing = authoritiesOf();
    const zones = zonesOf();
    const body: CapabilityMatrix = {
      groups: CATALOG.groups.map((group) => ({
        key: group.key,
        step: group.step,
        name: group.name,
        capabilities: CATALOG.capabilities
          .filter((cap) => cap.group === group.key)
          .map((cap) => ({
            key: cap.key,
            name: cap.name,
            levels: cap.levels.map((l) => l.level),
          })),
      })),
      employees: rows.map((row) => ({
        person: personOf(row.employee),
        roles: row.roles.map(roleRefOf),
        cells: Object.fromEntries(
          Object.entries(row.states).map(([key, s]) => [
            key,
            { level: s.level, partial: s.partial },
          ]),
        ),
        signing: signing.get(row.employee.id) ?? [],
        zones: zones.get(row.employee.id) ?? [],
        ...deputyOf(row.employee),
      })),
      signing_known: true,
      zones_known: true,
      warnings: warningsOf(rows),
      free_for_all: CATALOG.free_for_all,
    };
    return HttpResponse.json(body);
  }),

  http.get("*/admin/users/:id/capabilities", ({ params }) => {
    const denied = adminRead();
    if (denied) return denied;
    const employee = readEmployees().find((e) => e.id === params["id"]);
    if (!employee)
      return HttpResponse.json(
        { code: "NOT_FOUND", message: "Сотрудник не найден.", source: "bff" },
        { status: 404 },
      );
    return HttpResponse.json(
      cardOf(
        personOf(employee),
        rolesOfEmployee(employee),
        company(),
        toEmployee(employee).deputy,
        {
          signing: true,
          zones: true,
        },
      ),
    );
  }),

  http.get("*/me/capabilities", () => {
    const denied = guard();
    if (denied) return denied;
    const session = readSession();
    const me = session ? buildMe(session) : undefined;
    const actor = currentActor();
    if (!me || !actor) return forbidden();
    const employee = readEmployees().find((e) => e.id === me.id);
    const roles = rolesOf(
      me.roles.map((r) => r.id),
      readRoles(),
    );
    // Про себя: свои подпись и зоны читает любой сотрудник (`/signing/mine`, `/responsibility-zones/mine`).
    // «Нет доступа»: кто выдаёт возможности — те, у кого «Сотрудники и возможности» включено на «работать».
    const grantors = company()
      .filter((row) => row.states["staff"]?.on["manage"] === true)
      .map((row) => personOf(row.employee));
    return HttpResponse.json({
      ...cardOf(
        personOf({ id: me.id, name: me.name, initials: me.initials, position: me.position }),
        roles,
        null,
        employee ? toEmployee(employee).deputy : undefined,
        { signing: true, zones: true },
      ),
      grantors,
    });
  }),
];
