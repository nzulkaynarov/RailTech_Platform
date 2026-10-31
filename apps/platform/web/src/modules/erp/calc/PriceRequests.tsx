import { App, Button, Card } from "antd";
import { useTranslation } from "react-i18next";

import type { CalcSheet, PriceRequest } from "../../../shared/api/generated/model";
import {
  useAnswerPriceRequest,
  useListCalcPriceRequests,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { useErrorText, useRefreshStock, useStateLabels } from "../stock/api";
import { calcRef } from "./api";

function Entry({ item, canAnswer }: { item: PriceRequest; canAnswer: boolean }) {
  const { t } = useTranslation("stock");
  const { activity } = useFormat();
  const { message } = App.useApp();
  const refresh = useRefreshStock();
  const errorText = useErrorText();
  const answer = useAnswerPriceRequest({
    mutation: {
      onSuccess: () => {
        refresh();
      },
      onError: (error) => {
        void message.error(errorText(error));
      },
    },
  });
  return (
    <li>
      <div className="pf-calc-card-head">
        <strong>{item.supplier.name}</strong>
        {item.status === "failed" ? (
          <StatusTag kind="priceRequest" status="failed">
            {t("priceRequest.status.failed")}
          </StatusTag>
        ) : item.answered_at ? (
          <StatusTag kind="priceRequest" status="answered">
            {t("priceRequest.status.answered")}
          </StatusTag>
        ) : (
          <StatusTag kind="priceRequest" status="sent">
            {t("priceRequest.status.sent")}
          </StatusTag>
        )}
      </div>
      <p className="pf-hint">
        {t("priceRequest.entryMeta", {
          when: activity(item.requested_at),
          who: item.requested_by ?? "—",
          email: item.to_email,
        })}
      </p>
      <p>{item.lines.map((l) => `${l.name} · ${String(l.quantity)}`).join("; ")}</p>
      {item.error ? <p className="pf-hint">{item.error}</p> : null}
      {item.answer_note ? (
        <p className="pf-hint">{t("priceRequest.answerNote", { note: item.answer_note })}</p>
      ) : null}
      {canAnswer && item.status === "sent" && !item.answered_at ? (
        <Button
          size="small"
          loading={answer.isPending}
          aria-label={t("priceRequest.answerLabel", { name: item.supplier.name })}
          onClick={() => {
            answer.mutate({ requestId: item.id, data: {} });
          }}
        >
          {t("priceRequest.answer")}
        </Button>
      ) : null}
    </li>
  );
}

/** Журнал «Запросы цены у поставщиков» под таблицей строк расчёта: кто, когда, кому и по каким строкам; «Ответ получен». */
export function PriceRequests({ sheet }: { sheet: CalcSheet }) {
  const { t } = useTranslation("stock");
  const labels = useStateLabels();
  const query = useListCalcPriceRequests(calcRef(sheet.number));
  return (
    <Card size="small" title={<h2 className="pf-calc-title">{t("priceRequest.logTitle")}</h2>}>
      <QueryState query={query} labels={labels} level={3} compact>
        {(data) =>
          data.items.length === 0 ? (
            <p className="pf-hint">{t("priceRequest.logEmpty")}</p>
          ) : (
            <ul
              className="pf-calc-line-cards pf-stock-journal"
              aria-label={t("priceRequest.logTitle")}
            >
              {data.items.map((item) => (
                <Entry key={item.id} item={item} canAnswer={sheet.rights.stock === true} />
              ))}
            </ul>
          )
        }
      </QueryState>
    </Card>
  );
}
