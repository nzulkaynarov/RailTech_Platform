import { useTranslation } from "react-i18next";

import type { ConversationCard } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { channelLabel, factRows } from "./labels";

function Rows({ rows }: { rows: { label: string; value: string }[] }) {
  return (
    <dl className="pf-msg-card-list">
      {rows.map((row) => (
        <div key={row.label} className="pf-msg-card-row">
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Карточка лида для бокового окна (на 390 px — полноэкранный лист): контакты, каналы, согласие, факты квалификации от
 * бота и запрос. Пустые поля не показываются, кроме согласия — без него писать клиенту нельзя.
 */
export function LeadCard({ card }: { card: ConversationCard }) {
  const { t } = useTranslation("messages");
  const fmt = useFormat();
  const none = t("note.none");
  const contacts = [
    {
      label: t("card.telegram"),
      value: card.contacts.telegram ? `@${card.contacts.telegram}` : "",
    },
    { label: t("card.phone"), value: card.contacts.phone ?? "" },
    { label: t("card.email"), value: card.contacts.email ?? "" },
    { label: t("card.company"), value: card.contacts.company ?? "" },
  ].filter((row) => row.value);
  const about = [
    { label: t("card.channel"), value: channelLabel(t, card.channel) },
    { label: t("card.language"), value: t(`card.languages.${card.language}`) },
    {
      label: t("card.consent"),
      value: card.consent_given_at
        ? t("card.consentGiven", { date: fmt.date(card.consent_given_at) })
        : t("card.consentMissing"),
    },
    {
      label: t("card.client"),
      value: card.client_in_erp ? t("card.clientYes") : t("card.clientNo"),
    },
  ];
  const facts = factRows(t, card.facts);
  return (
    <div className="pf-msg-card">
      <h3 className="pf-msg-card-title">{card.name}</h3>
      <p className="pf-msg-card-sub">{card.lead}</p>
      <h4 className="pf-msg-card-h">{t("card.contacts")}</h4>
      {contacts.length ? <Rows rows={contacts} /> : <p className="pf-msg-card-none">{none}</p>}
      <Rows rows={about} />
      <h4 className="pf-msg-card-h">{t("card.facts")}</h4>
      {card.request ? <Rows rows={[{ label: t("card.request"), value: card.request }]} /> : null}
      {facts.length ? <Rows rows={facts} /> : <p className="pf-msg-card-none">{none}</p>}
    </div>
  );
}
