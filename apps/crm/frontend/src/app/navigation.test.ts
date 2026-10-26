import { describe, expect, it } from "vitest";

import type { PermissionsResponse } from "../api/generated/model";
import { homePath, navKeyOf, visibleNav } from "./navigation";

const matrix = (permissions: Record<string, Record<string, boolean>>) =>
  ({ permissions }) as unknown as PermissionsResponse;

const ALL = ["read", "write", "take", "use"];
const everything = (resources: string[]) =>
  matrix(
    Object.fromEntries(resources.map((r) => [r, Object.fromEntries(ALL.map((a) => [a, true]))])),
  );

const admin = everything([
  "leads",
  "clients",
  "deals",
  "dashboard",
  "spend",
  "kb",
  "settings",
  "reply_templates",
  "sandbox",
  "users",
  "integrations",
  "models",
  "system",
  "backups",
  "audit",
]);
const manager = matrix({
  leads: { read: true, take: true },
  clients: { read: true },
  deals: { read: true },
  dashboard: { read: true },
  kb: { read: true },
});
const viewer = matrix({
  leads: { read: true },
  clients: { read: true },
  deals: { read: true },
  dashboard: { read: true },
});

const shape = (groups: ReturnType<typeof visibleNav>) =>
  groups.map((g) => [g.key, g.items.join(",")]);

describe("menu IA (audit 2026-10-12)", () => {
  it("admin in admin mode sees four groups in task order", () => {
    expect(shape(visibleNav(admin, "admin"))).toEqual([
      ["work", "inbox,leads,clients,deals"],
      ["analytics", "dashboard,spend"],
      ["bot", "kb,gaps,sandbox,templates,settings"],
      ["admin", "users,integrations,models,system,backups,audit"],
    ]);
  });

  it("admin in manager mode sees the manager menu", () => {
    expect(shape(visibleNav(admin, "manager"))).toEqual([
      ["work", "inbox,leads,clients,deals"],
      ["analytics", "dashboard"],
      ["bot", "kb"],
    ]);
  });

  it("manager reads the knowledge base, without gaps and settings", () => {
    expect(shape(visibleNav(manager, "manager"))).toEqual([
      ["work", "inbox,leads,clients,deals"],
      ["analytics", "dashboard"],
      ["bot", "kb"],
    ]);
  });

  it("viewer has no inbox and no empty group headings", () => {
    expect(shape(visibleNav(viewer, "manager"))).toEqual([
      ["work", "leads,clients,deals"],
      ["analytics", "dashboard"],
    ]);
  });

  // Системный «Администратор» (R3-D-2): права на администрирование, без лидов, клиентов и дашборда.
  const sysAdmin = matrix({
    users: { read: true, write: true },
    integrations: { read: true, write: true },
    system: { read: true },
    audit: { read: true },
    settings: { read: true },
  });

  it.each([
    ["admin", admin, "/inbox"],
    ["admin without business rights", sysAdmin, "/users"],
    [
      "admin without users",
      matrix({ integrations: { read: true }, audit: { read: true } }),
      "/integrations",
    ],
    ["observer with clients only", matrix({ clients: { read: true } }), "/clients"],
    ["nothing at all", matrix({}), "/profile"],
    ["matrix not loaded", undefined, "/profile"],
    ["manager", manager, "/inbox"],
    ["viewer", viewer, "/dashboard"],
    ["nobody", matrix({ leads: { read: true } }), "/leads"],
  ])("%s starts at %s", (_role, perms, path) => {
    expect(homePath(perms)).toBe(path);
  });

  it.each([
    ["/leads/12", "leads"],
    ["/inbox", "inbox"],
    ["/profile", null],
    ["/", null],
  ])("%s highlights %s", (path, key) => {
    expect(navKeyOf(path)).toBe(key);
  });
});
