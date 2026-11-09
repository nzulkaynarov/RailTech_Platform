import { MemoList } from "./MemoList";
import { MemoView } from "./MemoView";
import { SigningList } from "./SigningList";

import "../decision/decision.css";

/** EDS · На согласовании: список `/eds/approvals` или карточка `/eds/approvals/:номер` (id документа или номер СЗ-2026/014). */
export function ApprovalsScreen({ objectId }: { objectId?: string | undefined }) {
  if (objectId) return <MemoView objectId={objectId} />;
  return (
    <>
      <SigningList />
      <MemoList />
    </>
  );
}
