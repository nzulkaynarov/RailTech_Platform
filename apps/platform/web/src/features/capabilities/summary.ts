import type { EmployeeCapabilities } from "../../shared/api/generated/model";
import { pickText } from "./model";

export interface SummaryLine {
  key: "does" | "decides" | "responsible" | "lacks";
  text: string;
}

/**
 * Четыре строки итога словами: что делает, что решает (тексты каталога из BFF), за что отвечает (зоны, если их читали) и чего не
 * может. Пустые не показываются: нет данных — нет строки, выдуманного «ничего» нет.
 */
export function summaryLines(data: EmployeeCapabilities, language: string): SummaryLine[] {
  const lines: SummaryLine[] = [];
  const { does, decides, lacks } = data.summary;
  if (does) lines.push({ key: "does", text: pickText(does, language) });
  if (decides) lines.push({ key: "decides", text: pickText(decides, language) });
  if (data.zones_known && data.zones.length > 0) {
    lines.push({
      key: "responsible",
      text: data.zones.map((zone) => pickText(zone.name, language)).join(", "),
    });
  }
  if (lacks) lines.push({ key: "lacks", text: pickText(lacks, language) });
  return lines;
}
