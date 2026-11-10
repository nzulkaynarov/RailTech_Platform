import { MemoView } from "./MemoView";

import "../decision/decision.css";

/** EDS · карточка согласования `/eds/approvals/:номер` (id документа или номер СЗ-2026/014); список — «Документы · Внутренние». */
export function ApprovalsScreen({ objectId }: { objectId?: string | undefined }) {
  return objectId ? <MemoView objectId={objectId} /> : null;
}
