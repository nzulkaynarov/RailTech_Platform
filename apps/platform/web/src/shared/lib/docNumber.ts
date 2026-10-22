/**
 * Бизнес-номера объектов (SPEC-v3 §2.2). Во внешних адресах и ссылках — только они, внутренних идентификаторов
 * бэкендов в интерфейсе нет. Разбор и сборка по одной таблице, чтобы формат жил в одном месте.
 */
export type DocKind =
  | "lead"
  | "incoming"
  | "request"
  | "project"
  | "quote"
  | "outgoing"
  | "contract"
  | "invoice"
  | "act"
  | "memo"
  | "supplierOrder";

interface DocSpec {
  prefix: string;
  /** Где в номере год: полный `ГГГГ` до порядкового номера, короткий `ГГ` после него или года нет */
  year: "full" | "short" | "none";
  /** Разделитель между годом и порядковым номером */
  join: "-" | "/";
  /** Минимальная ширина порядкового номера (с ведущими нулями) */
  width: number;
  /** КП несёт версию: `КП-2026/115 v2` */
  versioned?: boolean;
}

export const DOC_SPECS: Record<DocKind, DocSpec> = {
  lead: { prefix: "L", year: "none", join: "-", width: 4 },
  incoming: { prefix: "ВХ", year: "short", join: "/", width: 3 },
  request: { prefix: "ЗВ", year: "full", join: "-", width: 3 },
  project: { prefix: "ПР", year: "full", join: "-", width: 3 },
  quote: { prefix: "КП", year: "full", join: "/", width: 3, versioned: true },
  outgoing: { prefix: "ИСХ", year: "short", join: "/", width: 3 },
  contract: { prefix: "ДОГ", year: "full", join: "/", width: 3 },
  invoice: { prefix: "СЧ", year: "full", join: "/", width: 3 },
  act: { prefix: "АКТ", year: "full", join: "/", width: 3 },
  memo: { prefix: "СЗ", year: "full", join: "/", width: 3 },
  supplierOrder: { prefix: "ЗП", year: "full", join: "-", width: 3 },
};

export interface DocNumberParts {
  kind: DocKind;
  /** Полный год (для `ВХ-104/26` — 2026); у лида года нет */
  year?: number;
  seq: number;
  /** Версия КП: `v2` → 2 */
  version?: number;
}

const KINDS = Object.keys(DOC_SPECS) as DocKind[];

function pattern(spec: DocSpec): RegExp {
  const seq = `(\\d{${String(spec.width)},})`;
  const join = spec.join === "/" ? "\\/" : "-";
  const body =
    spec.year === "none"
      ? seq
      : spec.year === "full"
        ? `(\\d{4})${join}${seq}`
        : `${seq}\\/(\\d{2})`;
  return new RegExp(`^${spec.prefix}-${body}${spec.versioned ? "(?: v(\\d+))?" : ""}$`);
}

const PATTERNS = KINDS.map((kind) => [kind, pattern(DOC_SPECS[kind])] as const);

/** Разбирает номер; не номер → `null`. */
export function parseDocNumber(text: string): DocNumberParts | null {
  const value = text.trim();
  for (const [kind, regex] of PATTERNS) {
    const match = regex.exec(value);
    if (!match) continue;
    const spec = DOC_SPECS[kind];
    const version = spec.versioned && match[3] ? { version: Number(match[3]) } : {};
    if (spec.year === "none") return { kind, seq: Number(match[1]), ...version };
    if (spec.year === "full") {
      return { kind, year: Number(match[1]), seq: Number(match[2]), ...version };
    }
    return { kind, year: 2000 + Number(match[2]), seq: Number(match[1]) };
  }
  return null;
}

export function isDocNumber(text: string): boolean {
  return parseDocNumber(text) !== null;
}

/** Собирает номер: `{ kind: "request", year: 2026, seq: 104 }` → `ЗВ-2026-104`. */
export function formatDocNumber(parts: DocNumberParts): string {
  const spec = DOC_SPECS[parts.kind];
  const seq = String(parts.seq).padStart(spec.width, "0");
  const year = parts.year ?? 0;
  const version = spec.versioned && parts.version ? ` v${String(parts.version)}` : "";
  if (spec.year === "none") return `${spec.prefix}-${seq}`;
  if (spec.year === "full") return `${spec.prefix}-${String(year)}${spec.join}${seq}${version}`;
  return `${spec.prefix}-${seq}/${String(year % 100).padStart(2, "0")}`;
}

/** Проект наследует NNN заявки: `ЗВ-2026-104` → `ПР-2026-104`. Не заявка → `null`. */
export function projectNumberOf(requestNumber: string): string | null {
  const parts = parseDocNumber(requestNumber);
  return parts?.kind === "request" ? formatDocNumber({ ...parts, kind: "project" }) : null;
}

/** Часть адреса для номера: `ПР-2026-104` → `%D0%9F%D0%A0-2026-104` (BFF принимает бизнес-номер). */
export function docNumberToPath(number: string): string {
  return encodeURIComponent(number);
}
