import type { ReactNode } from "react";

import { useAuth } from "../../../app/auth/useAuth";
import type { RestrictedField } from "../../../shared/api/generated/model";

/**
 * Поле с ограничением (`platform-rbac.yaml` `restricted_fields`, CONVENTIONS.md §2 п. 6): показывается, только если роль видит
 * группу. BFF вырезает такие поля из ответа сам — это второй слой, чтобы пустой блок не оставался на экране.
 */
export function Restricted({ group, children }: { group: RestrictedField; children: ReactNode }) {
  const { me } = useAuth();
  return (me.restricted_fields ?? []).includes(group) ? <>{children}</> : null;
}
