import { useQueryClient } from "@tanstack/react-query";

import type { DocumentClientLinks } from "../../../shared/api/generated/model";
import {
  getGetPriceRequestPartnerLinksQueryKey,
  getGetSupplierOrderPartnerLinksQueryKey,
  useGetPriceRequestPartnerLinks,
  useGetSupplierOrderPartnerLinks,
  useRevokePriceRequestPartnerLinks,
  useRevokeSupplierOrderPartnerLinks,
} from "../../../shared/api/generated/platform-bff";
import { ClientLinkBlock, ClientLinkLoadError } from "../../../shared/ui/ClientLinkBlock";
import { summarizeLinks, type ClientLinkRow } from "../../../shared/ui/clientLinkState";

type Kind = "price_request" | "supplier_order";

interface Source {
  data: DocumentClientLinks | undefined;
  isError: boolean;
  refetch: () => unknown;
}

/**
 * Тот же блок «Ссылка в Кабинете», что у КП и договора (ДК-3б), но для партнёра (ДК-5): кому из контактов поставщика ушла
 * личная ссылка на запрос цены или заказ, открывал ли её и можно ли отозвать. Ссылок нет (документ партнёру с Кабинетом не
 * уходил) или нет права отправлять документ — блока нет совсем.
 */
function PartnerLinkView({
  kind,
  source,
  onRevoke,
}: {
  kind: Kind;
  source: Source;
  onRevoke: () => Promise<unknown>;
}) {
  const { data } = source;
  if (source.isError) {
    return (
      <ClientLinkLoadError
        partner
        onRetry={() => {
          void source.refetch();
        }}
      />
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
    <ClientLinkBlock
      kind={kind}
      state={state}
      expiresAt={expiresAt}
      rows={rows}
      canRevoke={data.can_revoke}
      onRevoke={onRevoke}
    />
  );
}

/** Ссылки партнёра на заказ поставщику «ЗП-…». */
export function OrderPartnerLinks({ number }: { number: string }) {
  const client = useQueryClient();
  const query = useGetSupplierOrderPartnerLinks(number);
  const revoke = useRevokeSupplierOrderPartnerLinks();
  return (
    <PartnerLinkView
      kind="supplier_order"
      source={query}
      onRevoke={() =>
        revoke.mutateAsync({ orderNumber: number }).then((next) => {
          client.setQueryData(getGetSupplierOrderPartnerLinksQueryKey(number), next);
        })
      }
    />
  );
}

/** Ссылки партнёра на запрос цены из журнала запросов расчёта. */
export function PriceRequestPartnerLinks({ requestId }: { requestId: string }) {
  const client = useQueryClient();
  const query = useGetPriceRequestPartnerLinks(requestId);
  const revoke = useRevokePriceRequestPartnerLinks();
  return (
    <PartnerLinkView
      kind="price_request"
      source={query}
      onRevoke={() =>
        revoke.mutateAsync({ requestId }).then((next) => {
          client.setQueryData(getGetPriceRequestPartnerLinksQueryKey(requestId), next);
        })
      }
    />
  );
}
