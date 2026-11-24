import { useQueryClient } from "@tanstack/react-query";

import {
  getGetEdsProjectDocumentClientLinksQueryKey,
  useGetEdsProjectDocumentClientLinks,
  useRevokeEdsProjectDocumentClientLinks,
} from "../../../shared/api/generated/platform-bff";
import { ClientLinkBlock } from "../../../shared/ui/ClientLinkBlock";
import { summarizeLinks, type ClientLinkRow } from "../../../shared/ui/clientLinkState";
import { ClientLinkLoadError } from "../../../shared/ui/ClientLinkBlock";
import { projectRef } from "./api";

type Kind = "contract" | "invoice" | "act";

/**
 * Ссылка клиента на договор, счёт или акт проекта в Кабинете (ДК-3б): тот же блок, что у КП, но со списком получателей.
 * Нет ссылок (документ клиенту не уходил) или нет права отправлять документ — блока нет совсем.
 */
export function DocumentClientLink({
  objectId,
  kind,
  documentId,
}: {
  objectId: string;
  kind: Kind;
  documentId: number;
}) {
  const ref = projectRef(objectId);
  const client = useQueryClient();
  const query = useGetEdsProjectDocumentClientLinks(ref, kind, documentId);
  const revoke = useRevokeEdsProjectDocumentClientLinks();
  const data = query.data;
  if (query.isError) {
    return (
      <li className="pf-doc pf-doc--detail">
        <ClientLinkLoadError onRetry={() => void query.refetch()} />
      </li>
    );
  }
  if (!data || data.links.length === 0) return null;

  const rows: ClientLinkRow[] = data.links.map((link) => ({
    key: `${link.sent_at}|${link.recipient_hint}`,
    hint: link.recipient_hint,
    sentAt: link.sent_at,
    openedAt: link.last_opened_at,
    state: link.state,
  }));
  const live = data.links.filter((link) => link.state === "active").map((link) => link.expires_at);
  const { state, expiresAt } = summarizeLinks(rows, live);
  return (
    <li className="pf-doc pf-doc--detail">
      <ClientLinkBlock
        kind={kind}
        state={state}
        expiresAt={expiresAt}
        rows={rows}
        canRevoke={data.can_revoke}
        onRevoke={() =>
          revoke.mutateAsync({ ref, kind, docId: documentId }).then((next) => {
            client.setQueryData(
              getGetEdsProjectDocumentClientLinksQueryKey(ref, kind, documentId),
              next,
            );
          })
        }
      />
    </li>
  );
}
