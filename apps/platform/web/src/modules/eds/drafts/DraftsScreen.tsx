import { QuoteList } from "./QuoteList";
import { QuoteView } from "./QuoteView";

import "../decision/decision.css";

/** EDS · КП на одобрение: список `/eds/drafts` или карточка `/eds/drafts/:номер` (id маршрута или номер КП-2026/115). */
export function DraftsScreen({ objectId }: { objectId?: string | undefined }) {
  return objectId ? <QuoteView objectId={objectId} /> : <QuoteList />;
}
