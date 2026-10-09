import { Link } from "react-router";

import { entityPath } from "../domain/entities";
import { entityLabel } from "../domain/labels";

export function EntityLink({ type, id }: { type: string; id: number | string | null | undefined }) {
  const text = id ? `${entityLabel(type)} #${String(id)}` : entityLabel(type);
  const path = entityPath(type, id);
  return path ? <Link to={path}>{text}</Link> : <>{text}</>;
}
