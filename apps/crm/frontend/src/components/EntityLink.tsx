import type { ReactNode } from "react";
import { Link } from "react-router";

import { entityPath, leadLinkText } from "../domain/entities";
import { entityLabel } from "../domain/labels";

type Id = number | string | null | undefined;

/** Ссылка на объект по типу: «Клиент #5»; без карточки — просто текст. */
export function EntityLink({ type, id, children }: { type: string; id: Id; children?: ReactNode }) {
  const text = children ?? (id ? `${entityLabel(type)} #${String(id)}` : entityLabel(type));
  const path = entityPath(type, id);
  return path ? <Link to={path}>{text}</Link> : <>{text}</>;
}

/**
 * Ссылка на карточку лида `#id · имя` — единый вид во входящих, списках, клиенте, пробелах.
 * `children` заменяет текст (например, «из лида»).
 */
export function LeadLink({
  id,
  name,
  children,
}: {
  id: number | string;
  name?: string | null;
  children?: ReactNode;
}) {
  return (
    <EntityLink type="lead" id={id}>
      {children ?? leadLinkText(id, name)}
    </EntityLink>
  );
}
