import { InboxList } from "./InboxList";
import { LetterView } from "./LetterView";

import "./inbox.css";

/** EDS · Входящие письма: список `/eds/inbox` или карточка `/eds/inbox/:номер` (id или номер ВХ-104/26). */
export function InboxScreen({ objectId }: { objectId?: string | undefined }) {
  return objectId ? <LetterView objectId={objectId} /> : <InboxList />;
}
