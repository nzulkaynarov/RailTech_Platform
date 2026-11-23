import { App, Button, Card } from "antd";
import { useTranslation } from "react-i18next";

import type { QuoteApprovalCard } from "../../../shared/api/generated/model";
import { useRevokeQuoteClientLink } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { useConfirmAction } from "../../../shared/ui/useConfirmAction";
import { useRefreshApprovals } from "../decision/errors";

/**
 * Ссылка клиента на отправленное КП в Кабинете (ДК-1): действует ли, кому ушла (адрес замаскирован), открывал ли клиент.
 * Тот, кто отправляет КП, может её отозвать — клиент по ссылке увидит только «ссылка отозвана»; новая отправка КП даёт
 * новую ссылку. Отзыв необратим для этой ссылки, поэтому спрашиваем один раз.
 */
export function ClientLinkCard({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const { date } = useFormat();
  const { message } = App.useApp();
  const confirmAction = useConfirmAction();
  const refresh = useRefreshApprovals();
  const revoke = useRevokeQuoteClientLink({
    mutation: {
      onSuccess: () => {
        void refresh();
        void message.success(t("card.clientLink.done"));
      },
      onError: () => {
        void message.error(t("card.clientLink.failed"));
      },
    },
  });
  const link = quote.client_link;
  if (!link) return null;

  const confirmRevoke = () => {
    confirmAction({
      action: t("card.clientLink.confirmAction"),
      object: t("card.clientLink.confirmObject"),
      summary: t("card.clientLink.confirmText"),
      danger: true,
      onConfirm: () => {
        revoke.mutate({ id: quote.id });
      },
    });
  };

  // «Ссылки нет» — только у state=none; живая ссылка без срока (КП без срока действия) — просто «действует».
  const state =
    link.state !== "active"
      ? t(`card.clientLink.state.${link.state}`)
      : link.expires_at
        ? t("card.clientLink.state.active", { date: date(link.expires_at, "date") })
        : t("card.clientLink.state.activeNoDate");
  return (
    <Card size="small" title={<h2 className="pf-dec-title">{t("card.clientLink.title")}</h2>}>
      <p className="pf-dec-note">{state}</p>
      {link.recipient_hint ? (
        <p className="pf-hint">{t("card.clientLink.to", { to: link.recipient_hint })}</p>
      ) : null}
      {link.state !== "none" ? (
        <p className="pf-hint">
          {link.last_opened_at
            ? t("card.clientLink.opened", { date: date(link.last_opened_at, "datetime") })
            : t("card.clientLink.notOpened")}
        </p>
      ) : null}
      {link.can_revoke ? (
        <div className="pf-dec-row">
          <Button danger loading={revoke.isPending} onClick={confirmRevoke}>
            {t("card.clientLink.revoke")}
          </Button>
        </div>
      ) : null}
    </Card>
  );
}
