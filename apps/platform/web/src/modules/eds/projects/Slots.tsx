import { useTranslation } from "react-i18next";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import type { ProjectCard } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { History, type HistoryItem } from "../../../shared/ui/History";
import { DecisionSlot } from "../decision/DecisionSlot";
import { ActPanel } from "./ActPanel";
import { ContractPanel } from "./ContractPanel";
import { journalText } from "./model";

/** Где живёт «Договор» проекта: вкладка бокового окна каркаса, на телефоне — лист на весь экран (`?sheet=contract`). */
export function ContractSlot({ card, objectId }: { card: ProjectCard; objectId: string }) {
  const { t } = useTranslation("projects");
  return (
    <DecisionSlot
      tab="contract"
      sheet="contract"
      title={
        card.contract
          ? t("panel.sheetContract", { number: card.contract.number })
          : t("panel.sheetContractNone")
      }
      label={t("panel.contractLabel")}
      closeLabel={t("panel.sheetClose")}
    >
      {(variant, onDone) => (
        <ContractPanel card={card} objectId={objectId} variant={variant} onDone={onDone} />
      )}
    </DecisionSlot>
  );
}

/** Где живёт «Акт» проекта: вкладка бокового окна, на телефоне — лист (`?sheet=act`). */
export function ActSlot({ card, objectId }: { card: ProjectCard; objectId: string }) {
  const { t } = useTranslation("projects");
  return (
    <DecisionSlot
      tab="act"
      sheet="act"
      title={card.act ? t("panel.sheetAct", { number: card.act.number }) : t("panel.sheetActNone")}
      label={t("panel.actLabel")}
      closeLabel={t("panel.sheetClose")}
    >
      {(variant, onDone) => (
        <ActPanel card={card} objectId={objectId} variant={variant} onDone={onDone} />
      )}
    </DecisionSlot>
  );
}

/** Журнал документов проекта: история договора, счетов и акта (новые первыми). */
export function JournalList({ card }: { card: ProjectCard }) {
  const { t } = useTranslation("projects");
  const { date } = useFormat();
  if (card.journal.length === 0) {
    return (
      <EmptyState level={3} compact title={t("panel.journalEmpty")} text={t("panel.journalHint")} />
    );
  }
  const items: HistoryItem[] = card.journal.map((entry) => ({
    state: "done",
    title: journalText(t, entry),
    meta: (
      <>
        {entry.actor_name
          ? t("journal.by", { date: date(entry.at, "datetime"), name: entry.actor_name })
          : t("journal.bySystem", { date: date(entry.at, "datetime") })}
        {entry.number ? <span> · {entry.number}</span> : null}
        {entry.reason ? (
          <span className="pf-dec-note">{t("journal.reason", { reason: entry.reason })}</span>
        ) : null}
      </>
    ),
  }));
  return <History items={items} label={t("card.journal.title")} />;
}

/** Вкладка «Журнал» бокового окна. */
export function JournalTab({ card }: { card: ProjectCard }) {
  return (
    <PanelPortal tab="journal">
      <div className="pf-dec-panel">
        <JournalList card={card} />
      </div>
    </PanelPortal>
  );
}
