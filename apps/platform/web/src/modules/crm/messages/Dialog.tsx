import { Alert, Button, Drawer, Spin } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import type { ConversationCard, MessageInboxItem } from "../../../shared/api/generated/model";
import { useGetCrmConversation } from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { withParams } from "../kb/refresh";
import { useLeadActions } from "./actions";
import { Composer } from "./Composer";
import { HandoffNoteBox } from "./HandoffNoteBox";
import { channelLabel } from "./labels";
import { LeadCard } from "./LeadCard";
import { canTake } from "./logic";
import { Thread } from "./Thread";

function ownerText(
  t: (key: string, values?: Record<string, string>) => string,
  card: ConversationCard,
  me: string,
) {
  if (card.owner_mode === "manager") {
    return card.assigned?.id === me
      ? t("owner.you")
      : t("owner.manager", { name: card.assigned?.name ?? "—" });
  }
  return t(`owner.${card.owner_mode}`);
}

function Actions({
  card,
  item,
  canReply,
}: {
  card: ConversationCard;
  item?: MessageInboxItem;
  canReply: boolean;
}) {
  const { t } = useTranslation("messages");
  const { me } = useAuth();
  const actions = useLeadActions(card.lead);
  if (!canReply) return null;
  const takeable = item ? canTake(item) : card.owner_mode === "waiting" && !card.assigned;
  const mine = card.owner_mode === "manager" && card.assigned?.id === me.id;
  return (
    <>
      {takeable ? (
        <Button type="primary" loading={actions.taking} onClick={actions.take}>
          {t("actions.take")}
        </Button>
      ) : null}
      {mine ? (
        <Button loading={actions.returning} onClick={actions.returnToBot}>
          {t("actions.returnToBot")}
        </Button>
      ) : null}
    </>
  );
}

/**
 * Диалог лида: шапка (имя, канал, кто ведёт, «Забрать» / «Вернуть боту»), записка передачи, лента и поле ответа. Карточка
 * лида — в боковом окне; на 390 px диалог занимает экран (назад — «Все диалоги»), карточка — полноэкранный лист с кнопками
 * внизу.
 */
export function Dialog({
  lead,
  item,
  canReply,
  mobile,
}: {
  lead: string;
  item?: MessageInboxItem;
  canReply: boolean;
  mobile: boolean;
}) {
  const { t } = useTranslation("messages");
  const { me } = useAuth();
  const [params] = useSearchParams();
  const [sheet, setSheet] = useState(false);
  const conversation = useGetCrmConversation(lead);
  const card = conversation.data;

  if (conversation.isPending) {
    return (
      <section className="pf-msg-dialog pf-msg-center">
        <Spin />
      </section>
    );
  }
  if (!card) {
    return (
      <section className="pf-msg-dialog">
        <Alert type="error" showIcon message={t("errors.NOT_FOUND")} />
      </section>
    );
  }
  const takeable = canReply && (item ? canTake(item) : false);
  return (
    <section className="pf-msg-dialog" aria-labelledby="pf-msg-dialog-title">
      <header className="pf-msg-dialog-head">
        {mobile ? (
          <Link className="pf-msg-back" to={withParams(params, { lead: null, panel: null })}>
            ‹ {t("actions.back")}
          </Link>
        ) : null}
        <div className="pf-msg-dialog-title">
          <h2 id="pf-msg-dialog-title">{card.name}</h2>
          <p>
            {card.lead} · {channelLabel(t, card.channel)} · {ownerText(t, card, me.id)}
          </p>
        </div>
        <div className="pf-msg-dialog-actions">
          {mobile ? (
            <Button
              onClick={() => {
                setSheet(true);
              }}
            >
              {t("actions.card")}
            </Button>
          ) : null}
          {mobile ? null : <Actions card={card} item={item} canReply={canReply} />}
        </div>
      </header>
      {takeable && !mobile ? <Consequence items={[t("consequence.take")]} /> : null}
      {item ? <HandoffNoteBox note={item.note} handoff={item.handoff} /> : null}
      <Thread lead={lead} name={card.name} canReply={canReply} />
      {canReply ? (
        <Composer card={card} />
      ) : (
        <p className="pf-msg-readonly">{t("composer.readOnly")}</p>
      )}
      {mobile ? (
        <Drawer
          open={sheet}
          placement="bottom"
          height="100%"
          title={t("card.title")}
          onClose={() => {
            setSheet(false);
          }}
          closable={false}
          styles={{ body: { padding: 16 } }}
          footer={
            <div className="pf-msg-sheet-foot">
              <Actions card={card} item={item} canReply={canReply} />
              <Button
                onClick={() => {
                  setSheet(false);
                }}
              >
                {t("actions.close")}
              </Button>
            </div>
          }
        >
          <LeadCard card={card} />
        </Drawer>
      ) : (
        <PanelPortal tab="card">
          <LeadCard card={card} />
        </PanelPortal>
      )}
    </section>
  );
}
