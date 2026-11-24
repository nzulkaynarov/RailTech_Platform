import type { QuoteApprovalCard } from "../../../shared/api/generated/model";
import { useRevokeQuoteClientLink } from "../../../shared/api/generated/platform-bff";
import { ClientLinkBlock } from "../../../shared/ui/ClientLinkBlock";
import { useRefreshApprovals } from "../decision/errors";

/**
 * Ссылка клиента на отправленное КП в Кабинете (ДК-1): общий блок `ClientLinkBlock`; у КП в карточке одна сводка
 * по всем ссылкам получателей, а не список.
 */
export function ClientLinkCard({ quote }: { quote: QuoteApprovalCard }) {
  const refresh = useRefreshApprovals();
  const revoke = useRevokeQuoteClientLink();
  const link = quote.client_link;
  if (!link) return null;
  return (
    <ClientLinkBlock
      kind="quote"
      state={link.state}
      expiresAt={link.expires_at}
      rows={[
        {
          key: "quote",
          hint: link.recipient_hint,
          openedAt: link.last_opened_at,
        },
      ]}
      canRevoke={link.can_revoke}
      onRevoke={() => revoke.mutateAsync({ id: quote.id }).then(() => refresh())}
    />
  );
}
