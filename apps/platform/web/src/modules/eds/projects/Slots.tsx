import { useTranslation } from "react-i18next";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import type { ProjectCard } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { CompanyCell } from "../../../shared/ui/EntityCell";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PersonRefCell } from "../../PersonRefCell";
import { RecordHistory } from "../../../shared/ui/RecordHistory";
import { projectHistoryEntries } from "./model";

const HISTORY_FILTERS = ["quote", "contract", "invoice", "act"] as const;

/**
 * Вкладка «История» бокового окна: журнал проекта один — договор, счета, акт и КП в нём чипами-фильтрами, а не копиями
 * (ЕД-7). Записей нет — вкладки нет.
 */
export function ProjectHistoryTab({ card }: { card: ProjectCard }) {
  const { t } = useTranslation("projects");
  if (card.journal.length === 0) return null;
  return (
    <PanelPortal tab="history">
      <div className="pf-dec-panel">
        <RecordHistory
          label={t("card.journal.title")}
          entries={projectHistoryEntries(t, card)}
          filters={HISTORY_FILTERS.map((key) => ({
            key,
            label: t(`card.documents.${key}`),
          }))}
        />
      </div>
    </PanelPortal>
  );
}

/** Вкладка «Сведения»: реквизиты клиента и проекта — единственное место, где они перечислены (ЕД-7). */
export function ProjectFactsTab({ card }: { card: ProjectCard }) {
  const { t } = useTranslation("projects");
  const { date } = useFormat();
  return (
    <PanelPortal tab="facts">
      <div className="pf-dec-panel">
        <DefinitionList
          items={[
            {
              label: t("card.fields.client"),
              value: <CompanyCell name={card.client_name} logoUrl={card.client_logo_url ?? null} />,
            },
            {
              label: t("card.fields.total"),
              value: card.total ? (
                <MoneyText value={card.total.amount} currency={card.total.currency} />
              ) : null,
            },
            {
              label: t("card.fields.manager"),
              value: card.manager ? (
                <PersonRefCell
                  person={{ id: String(card.manager.id), name: card.manager.name }}
                  caption={null}
                />
              ) : null,
            },
            {
              label: t("card.fields.responsible"),
              value: card.responsible ? (
                <PersonRefCell
                  person={{ id: String(card.responsible.id), name: card.responsible.name }}
                  caption={null}
                />
              ) : null,
            },
            { label: t("card.fields.opened"), value: date(card.created_at) },
            { label: t("card.fields.due"), value: card.due_date ? date(card.due_date) : null },
          ]}
        />
      </div>
    </PanelPortal>
  );
}
