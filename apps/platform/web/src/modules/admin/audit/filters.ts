export interface AuditFilterValues {
  actor: string;
  action: string;
  entityType: string;
  from: string;
  to: string;
  logins: boolean;
}

export const NO_FILTERS: AuditFilterValues = {
  actor: "",
  action: "",
  entityType: "",
  from: "",
  to: "",
  logins: false,
};

export const hasFilters = (v: AuditFilterValues, entityId: string | null) =>
  Boolean(v.actor || v.action || v.entityType || v.from || v.to || v.logins || entityId);
