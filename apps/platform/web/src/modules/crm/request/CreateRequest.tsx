import { Button, Radio, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import { useGetCrmLead } from "../../../shared/api/generated/platform-bff";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { canCreateFromLead } from "../common/access";
import { PartnerHandoff } from "./PartnerHandoff";
import { type LetterSource, RequestForm } from "./RequestForm";
import type { LeadCard } from "../../../shared/api/generated/model";

type Who = "client" | "partner";

/**
 * Форма «Создать заявку» из лида (`lead`) или из карточки клиента (`clientId`): для лида сначала читается его карточка —
 * контакты, согласие и запрос, собранный ботом, заполняют форму. Лид без клиента сначала спрашивает «Кто это?» (ЛП-1):
 * «Клиент» — заявка клиента, «Партнёр» — заявка кандидата в партнёры; лид с партнёрской формы сайта начинает с «Партнёр».
 */
export function CreateRequest({
  lead,
  clientId,
  letterFrom = null,
  onCancel,
}: {
  lead: string | null;
  clientId: number | null;
  /** Вложение сообщения лида — письмо директору («В заявку» в «Ждут ответа») */
  letterFrom?: LetterSource | null;
  onCancel: () => void;
}) {
  const { t } = useTranslation(["leads", "request"]);
  const { me } = useAuth();
  const card = useGetCrmLead(lead ?? "", { query: { enabled: lead !== null } });
  if (lead === null) return <RequestForm lead={null} clientId={clientId} onCancel={onCancel} />;
  if (card.isPending) return <Skeleton active paragraph={{ rows: 6 }} title={false} />;
  if (card.isError) {
    return (
      <EmptyState
        level={3}
        compact
        title={t("leads:loadError.title")}
        text={t("leads:loadError.text")}
      />
    );
  }
  // Чужой лид (адрес `create=1` вручную или устаревшая ссылка): формы нет — и вложение из переписки в EDS не копируется.
  if (!canCreateFromLead(me, card.data.assigned)) {
    return (
      <EmptyState
        level={3}
        compact
        title={t("request:title")}
        text={t("request:errors.not_lead_owner")}
      />
    );
  }
  // Лид из Telegram без согласия: отметить его здесь нельзя (согласие даётся в боте) — причина вместо формы, до заполнения.
  if (card.data.channel === "telegram" && card.data.consent.given_at === null) {
    return (
      <EmptyState level={3} compact title={t("request:title")} text={t("request:consent.viaBot")} />
    );
  }
  return (
    <LeadStep card={card.data} clientId={clientId} letterFrom={letterFrom} onCancel={onCancel} />
  );
}

/**
 * Шаг после загрузки карточки. Вопрос «Кто это?» и «уже передан» решаются по карточке в момент открытия (`useState`
 * запоминает их): после отправки карточка обновится (клиент, партнёр), а экран «готово» должен остаться на месте.
 */
function LeadStep({
  card,
  clientId,
  letterFrom,
  onCancel,
}: {
  card: LeadCard;
  clientId: number | null;
  letterFrom: LetterSource | null;
  onCancel: () => void;
}) {
  const { t } = useTranslation("request");
  const [opened] = useState(() => ({
    // Письмо из переписки и лид, уже связанный с клиентом, — путь клиента: вопроса нет.
    asks: card.client === null && letterFrom === null,
    handed: card.partner_application != null,
    partnerForm: card.origin?.form === "site-partner",
  }));
  const [chosen, setChosen] = useState<Who | null>(null);
  // Заявка заведена — вопрос «Кто это?» убираем: ответ уже дан, остаётся экран результата
  const [finished, setFinished] = useState(false);
  // Лид уже передан как партнёр (повторный адрес, вторая вкладка): заявка есть, второй формы нет.
  if (opened.handed) {
    return (
      <EmptyState
        level={3}
        compact
        title={t("partner.done.title")}
        text={t("partner.done.repeated")}
        action={<Button onClick={onCancel}>{t("partner.done.close")}</Button>}
      />
    );
  }
  const who: Who = !opened.asks
    ? "client"
    : (chosen ?? (opened.partnerForm ? "partner" : "client"));
  const form =
    who === "partner" ? (
      <PartnerHandoff
        lead={card}
        onCancel={onCancel}
        onDone={() => {
          setFinished(true);
        }}
      />
    ) : (
      <RequestForm
        lead={card}
        clientId={clientId}
        letterFrom={letterFrom}
        onCreated={() => {
          setFinished(true);
        }}
        onCancel={onCancel}
      />
    );
  if (!opened.asks) return form;
  return (
    <div className="pf-fp-stack">
      {/* Обёртка и форма остаются на месте и после ответа: иначе форма пересоздалась бы и потеряла экран «готово» */}
      {finished ? null : (
        <fieldset className="pf-req-group">
          <legend>{t("who.legend")}</legend>
          <Radio.Group
            value={who}
            onChange={(event) => {
              setChosen(event.target.value as Who);
            }}
            options={[
              { value: "client", label: t("who.client") },
              { value: "partner", label: t("who.partner") },
            ]}
          />
        </fieldset>
      )}
      {form}
    </div>
  );
}
