/**
 * Отметки «Тестовая» (ТЕСТ-1) на моках: ставятся в карточке контрагента, а список клиентов, список партнёров и карточки читают
 * их отсюда — как ERP отдаёт отметку одной компании во все экраны. Ключ — id компании ERP.
 */
const tests = new Set<string>();

export type TestScope = "only" | "all" | null;

export function isTest(companyId: string): boolean {
  return tests.has(companyId);
}

export function setTest(companyId: string): void {
  tests.add(companyId);
}

export function clearTest(companyId: string): void {
  tests.delete(companyId);
}

/** Сброс между тестами и сценариями. */
export function resetTests(): void {
  tests.clear();
}

/** Список по `?test=`: без параметра — без тестовых, `only` — только они, `all` — все. */
export function inScope(companyId: string | null, scope: string | null): boolean {
  if (scope === "all") return true;
  const marked = companyId !== null && tests.has(companyId);
  return scope === "only" ? marked : !marked;
}
