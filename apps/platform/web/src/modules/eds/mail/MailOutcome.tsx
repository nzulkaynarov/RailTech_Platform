import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { InboundMailResult } from "../../../shared/api/generated/model";

/** Итог «Разобрано» словами: ВХ и лид — ссылкой, ответ, архив с причиной. */
export function MailOutcome({ result }: { result: InboundMailResult }) {
  const { t } = useTranslation("letters");
  const number = result.letter_number;
  if (result.outcome === "registered" && number) {
    const text = t("mail.outcome.registered", { number });
    return result.letter_ref ? <Link to={result.letter_ref}>{text}</Link> : <>{text}</>;
  }
  if (result.outcome === "lead" && result.lead) {
    const text = t("mail.outcome.lead", { number: result.lead.number });
    return (
      <Link to={`/crm/leads?lead=${encodeURIComponent(result.lead.number)}&panel=open&tab=card`}>
        {text}
      </Link>
    );
  }
  if (result.outcome === "replied") return <>{t("mail.outcome.replied")}</>;
  if (result.outcome === "price") return <>{t("mail.outcome.price")}</>;
  if (result.outcome === "archived") {
    return <>{t("mail.outcome.archived", { reason: result.reason ?? "—" })}</>;
  }
  return <>{t("mail.outcome.unknown")}</>;
}
