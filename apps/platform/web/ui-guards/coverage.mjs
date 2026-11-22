// Weekly number for PR bodies (ЕВ-1а): "screens on the shared frame N of M; violations by kind".
// Usage: pnpm ui:coverage   (from apps/platform/web)
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import {
  ALL_KINDS,
  GUARDED_DIRS,
  WEB_ROOT,
  isGuardedTs,
  loadAllowlist,
  webPath,
} from "./detect.mjs";

function files(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) files(full, out);
    else out.push(full);
  }
  return out;
}

/** Table call sites in module code: `<RegistryTable` (shared frame) vs `<DataTable` (bare table, own frame). */
export function countSites() {
  let framed = 0;
  let bare = 0;
  for (const dir of GUARDED_DIRS) {
    for (const full of files(join(WEB_ROOT, dir))) {
      if (!isGuardedTs(webPath(full))) continue;
      const text = readFileSync(full, "utf8");
      framed += (text.match(/<RegistryTable\b/g) ?? []).length;
      bare += (text.match(/<DataTable\b/g) ?? []).length;
    }
  }
  return { framed, total: framed + bare };
}

export function report() {
  const { framed, total } = countSites();
  const allow = loadAllowlist();
  const kinds = ALL_KINDS.map((kind) => `${kind} ${String((allow[kind] ?? []).length)}`).join(
    " · ",
  );
  const sum = ALL_KINDS.reduce((n, kind) => n + (allow[kind] ?? []).length, 0);
  return `screens on the shared frame ${String(framed)} of ${String(total)} (table call sites in module code); violations by kind (files): ${kinds}; total ${String(sum)}`;
}

if (import.meta.url === `file://${process.argv[1]}`) console.log(report());
