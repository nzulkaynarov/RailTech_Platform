import { QuoteView } from "./QuoteView";

import "../decision/decision.css";

/** EDS · карточка КП `/eds/drafts/:номер` (id маршрута или номер КП-2026/115); список — «Документы · Исходящие». */
export function DraftsScreen({ objectId }: { objectId?: string | undefined }) {
  return objectId ? <QuoteView objectId={objectId} /> : null;
}
