import type { DoNotWork } from "../shared/api/generated/model";
import { resetTests } from "./testMarks";

/**
 * Отметки «Не работать» (Х-8) на моках: ставятся в карточке контрагента, а списки, карточка клиента и карточка проекта
 * читают их отсюда — как ERP отдаёт факты одной компании во все экраны. Ключ — id компании ERP; по названию — для карточки
 * проекта, которая знает только клиента.
 */
const marks = new Map<string, { name: string; mark: DoNotWork }>();

export function markOf(companyId: string): DoNotWork | null {
  return marks.get(companyId)?.mark ?? null;
}

export function markOfName(name: string): DoNotWork | null {
  for (const entry of marks.values()) if (entry.name === name) return entry.mark;
  return null;
}

export function setMark(companyId: string, name: string, mark: DoNotWork): void {
  marks.set(companyId, { name, mark });
}

export function clearMark(companyId: string): void {
  marks.delete(companyId);
}

/** Сброс между тестами и сценариями. */
export function resetMarks(): void {
  marks.clear();
  resetTests();
}
