/** Какой текст плашки: один источник — его ключ, CRM и ERP — `both`, всё остальное (с EDS) — `multi`. */
export function bannerKind(
  crm: boolean,
  erp: boolean,
  eds: boolean,
): "crm" | "erp" | "eds" | "both" | "multi" {
  const down = [crm, erp, eds].filter(Boolean).length;
  if (down > 1) return crm && erp && !eds ? "both" : "multi";
  return crm ? "crm" : erp ? "erp" : "eds";
}
