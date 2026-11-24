import { Button } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useGetCrmClientTelegramGroup } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { Thread } from "../messages/Thread";
import { GroupState } from "./GroupState";

import "../messages/messages.css";
import "./telegram-group.css";

/**
 * Раздел «Группа с клиентом» карточки клиента (ТГ-1б, ADR-0032): название группы, с какого дня она подключена, состояние и
 * «Переписка группы» — лента группы в карточке, только чтение (ответ из Платформы — ТГ-2). Группы нет — раздела нет.
 * Ленту читает тот, кто видит диалоги (`crm.leads` или `chats.external`); у остальных раздел без ссылки на ленту.
 */
export function ClientGroupSection({ clientId }: { clientId: number }) {
  const { t } = useTranslation("clients");
  const { me } = useAuth();
  const fmt = useFormat();
  const headingId = useId();
  const [open, setOpen] = useState(false);
  const query = useGetCrmClientTelegramGroup(clientId);
  const group = query.data?.group;
  if (!group) return null;
  const reads = canSee(me, { resource: "crm.leads" }) || canSee(me, { resource: "chats.external" });
  return (
    <section className="pf-fp-block" aria-labelledby={headingId}>
      <h4 id={headingId}>{t("tgGroups.card.title")}</h4>
      <DefinitionList
        items={[
          { label: t("tgGroups.card.name"), value: group.title },
          {
            label: t("tgGroups.card.since"),
            value: group.bound_at ? fmt.date(group.bound_at) : null,
          },
          { label: t("tgGroups.card.state"), value: <GroupState state={group.state} /> },
        ]}
      />
      {reads && group.lead ? (
        <div className="pf-tgg-card-actions">
          <Button
            type="link"
            style={{ padding: 0 }}
            aria-expanded={open}
            onClick={() => {
              setOpen((value) => !value);
            }}
          >
            {t(open ? "tgGroups.card.close" : "tgGroups.card.open")}
          </Button>
        </div>
      ) : null}
      {open && group.lead ? (
        <div className="pf-tgg-feed">
          <Thread lead={group.lead} name={group.title} />
          <p className="pf-hint">{t("tgGroups.card.replyInGroup")}</p>
        </div>
      ) : null}
    </section>
  );
}
