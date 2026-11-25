import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { CalcRequestCard } from "../../../shared/api/generated/model";
import { useGetCalcRequestCard } from "../../../shared/api/generated/platform-bff";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { calcRef, useStateLabels } from "./api";
import { ClosedNote, CloseRequestButton } from "./CloseRequest";
import { RequestFiles } from "./RequestFiles";

import "./calc.css";

function Body({ card, titled }: { card: CalcRequestCard; titled: boolean }) {
  const { t } = useTranslation(["calc", "dictionary"]);
  return (
    <div className="pf-calc-task">
      <div className="pf-calc-task-brief">
        {titled ? (
          <h3 className="pf-calc-task-title">
            {t("calc:close.draftTitle", { number: card.number })}
          </h3>
        ) : null}
        <p className="pf-hint">{card.title}</p>
      </div>
      <ClosedNote close={card.close} />
      <DefinitionList
        items={[
          { label: t("calc:close.client"), value: card.client ?? "—" },
          { label: t("calc:close.stage"), value: t(`dictionary:stage.${card.step}`) },
          { label: t("calc:close.textRequest"), value: card.request.text || "—" },
        ]}
      />
      {card.request.files?.length ? <RequestFiles sheet={card} /> : null}
      {card.has_task ? null : <p className="pf-hint">{t("calc:close.draftHint")}</p>}
      <div>
        <CloseRequestButton target={card} />
      </div>
    </div>
  );
}

/**
 * Карточка заявки без расчёта (черновик из передачи лида, задания расчёта ещё нет): текст, клиент, шаг и «Закрыть заявку».
 * Нет такой заявки вовсе — «заявки нет среди заданий».
 */
export function RequestCard({ number, compact = false }: { number: string; compact?: boolean }) {
  const { t } = useTranslation("calc");
  const query = useGetCalcRequestCard(calcRef(number));
  const labels = useStateLabels();
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <EmptyState
        level={3}
        compact={compact}
        title={t("load.notFound.title")}
        text={t("load.notFound.text")}
      />
    );
  }
  return (
    <QueryState query={query} labels={labels} level={3} compact={compact}>
      {(card) => <Body card={card} titled={compact} />}
    </QueryState>
  );
}
