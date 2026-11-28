import type {
  CapabilityLevel,
  CapabilityText,
  EmployeeCapabilities,
} from "../../shared/api/generated/model";
import { pickText, rank } from "./model";

/** Самая длинная строка сводки (знаков, вместе с подписью) и самое большое число названий в ней. */
export const LINE_MAX = 90;
export const ITEMS_MAX = 6;

/** Высший уровень человека в области: самый высокий из её возможностей («не всё» — только в строках возможностей). */
export function areaLevel(cells: readonly { level: CapabilityLevel }[]): CapabilityLevel {
  let top: CapabilityLevel = "none";
  for (const cell of cells) if (rank(cell.level) > rank(top)) top = cell.level;
  return top;
}

/** «Лиды и клиенты» → «лиды и клиенты»; сокращения («КП», «ИИ») остаются как есть. */
export function soft(name: string): string {
  const [first = "", second = ""] = name;
  return second !== "" && second === second.toLocaleLowerCase() && first !== second
    ? first.toLocaleLowerCase() + name.slice(1)
    : name;
}

export type SummaryKey = "does" | "decides" | "responsible" | "lacks";

export interface SummaryItems {
  key: SummaryKey;
  items: string[];
}

interface Row {
  name: CapabilityText;
  level: CapabilityLevel;
  partial: boolean;
}

/**
 * Итог словами по ОБЛАСТЯМ сделки, а не по возможностям: «Ведёт», «Решает», «Отвечает за» (если зоны есть), «Не может».
 * Область, где у человека всё на нужном уровне и ни одна строка не «не всё», называется целиком; иначе — её возможностями. Пустая строка не выдаётся;
 * нет данных (зоны не читались) — нет строки.
 */
export function summaryItems(data: EmployeeCapabilities, language: string): SummaryItems[] {
  const does: string[] = [];
  const decides: string[] = [];
  const lacks: string[] = [];
  for (const group of data.groups) {
    const rows: Row[] = group.rows.map((row) => ({
      name: row.name,
      level: row.level,
      partial: row.partial,
    }));
    const area = soft(pickText(group.name, language));
    const collect = (into: string[], test: (level: CapabilityLevel) => boolean) => {
      const hit = rows.filter((row) => test(row.level));
      if (hit.length === 0) return;
      if (hit.length === rows.length && !hit.some((row) => row.partial)) into.push(area);
      else for (const row of hit) into.push(soft(pickText(row.name, language)));
    };
    collect(does, (level) => rank(level) >= rank("work"));
    collect(decides, (level) => level === "decide");
    collect(lacks, (level) => level === "none");
  }
  const out: SummaryItems[] = [];
  if (does.length > 0) out.push({ key: "does", items: does });
  if (decides.length > 0) out.push({ key: "decides", items: decides });
  if (data.zones_known && data.zones.length > 0) {
    out.push({
      key: "responsible",
      items: [...new Set(data.zones.map((zone) => soft(pickText(zone.name, language))))],
    });
  }
  if (lacks.length > 0) out.push({ key: "lacks", items: lacks });
  return out;
}

/** Сколько названий влезает в строку: не больше `ITEMS_MAX` и в `LINE_MAX` знаков вместе с подписью и «и ещё N». */
export function fitItems(label: string, items: readonly string[], moreText: (n: number) => string) {
  const shown: string[] = [];
  let length = label.length + 2 + 1; // «Ведёт: » и точка в конце
  for (const item of items) {
    const rest = items.length - shown.length - 1;
    const tail = rest > 0 ? moreText(rest).length + 3 : 0;
    const add = (shown.length > 0 ? 2 : 0) + item.length;
    if (shown.length >= ITEMS_MAX || length + add + tail > LINE_MAX) break;
    shown.push(item);
    length += add;
  }
  if (shown.length === 0 && items[0] !== undefined) shown.push(items[0]);
  return { shown, hidden: items.length - shown.length };
}
