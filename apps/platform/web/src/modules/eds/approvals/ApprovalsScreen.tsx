import { MemoList } from "./MemoList";
import { MemoView } from "./MemoView";

import "../decision/decision.css";

/** EDS · На согласовании: список `/eds/approvals` или карточка `/eds/approvals/:номер` (id документа или номер СЗ-2026/014). */
export function ApprovalsScreen({ objectId }: { objectId?: string | undefined }) {
  return objectId ? <MemoView objectId={objectId} /> : <MemoList />;
}
