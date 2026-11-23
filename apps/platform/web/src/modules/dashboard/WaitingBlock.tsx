import { App, Button } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { WaitingRow } from "../../shared/api/generated/model";
import { useGetQueueWaiting, useRemindQueueWaiting } from "../../shared/api/generated/platform-bff";
import { ApiError } from "../../shared/api/errors";
import { usePollQuery } from "../../shared/api/polling";
import { useFormat } from "../../shared/lib/useFormat";
import { objectLink } from "../objectLinks";
import { ageOf, canRemind } from "./queueModel";

/** Кого ждём: «на подписи у Имени», «на согласовании: Бухгалтер», «поручение: Имя · срок 20.01». */
function useWho() {
  const { t } = useTranslation("modules");
  const format = useFormat();
  return (row: WaitingRow, now: number): string => {
    const name = row.waiting_on?.name ?? row.waiting_label ?? "";
    const base =
      row.kind === "letter_signature"
        ? row.waiting_on
          ? t("dashboard.queue.waiting.onSignature", { name })
          : t("dashboard.queue.waiting.noSigner")
        : row.kind === "approval"
          ? t("dashboard.queue.waiting.onApproval", { name })
          : t("dashboard.queue.waiting.onInstruction", { name });
    const age = ageOf(row.since, now);
    return [
      base,
      row.due_at
        ? t("dashboard.queue.waiting.until", { date: format.date(row.due_at, "short") })
        : null,
      t(`dashboard.queue.waiting.age.${age.unit}`, { count: age.count }),
    ]
      .filter(Boolean)
      .join(" · ");
  };
}

/**
 * «Вы ждёте других» (ГЛ-1): что вы передали и ждёте не от себя; строка гаснет сама, когда подписано, решено или исполнено.
 * «Напомнить» повторяет уведомление адресату — не чаще раза в час, дальше кнопка неактивна, пока EDS не разрешит.
 */
export function WaitingBlock() {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const client = useQueryClient();
  const poll = usePollQuery();
  const waiting = useGetQueueWaiting({ query: poll });
  const who = useWho();
  // «Сейчас» — момент последнего ответа BFF: он обновляется опросом, часов в отрисовке нет
  const nowMs = waiting.dataUpdatedAt;
  const remind = useRemindQueueWaiting({
    mutation: {
      onSuccess: () => {
        void message.success(t("dashboard.queue.waiting.reminded"));
      },
      onError: (failure) => {
        void message.warning(
          failure instanceof ApiError && failure.status === 429
            ? t("dashboard.queue.waiting.again")
            : t("dashboard.queue.waiting.failed"),
        );
      },
      onSettled: () =>
        client.invalidateQueries({
          predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/queue/waiting"),
        }),
    },
  });
  const items = waiting.data?.items ?? [];
  if (waiting.isError) {
    return (
      <section className="pf-card pf-waiting" aria-label={t("dashboard.queue.waiting.title")}>
        <p className="pf-hint pf-waiting-note">{t("dashboard.queue.waiting.loadError")}</p>
      </section>
    );
  }
  if (items.length === 0) return null;
  return (
    <section className="pf-card pf-waiting" aria-labelledby="pf-waiting-title">
      <div className="pf-card-head">
        <h2 id="pf-waiting-title" className="pf-card-title">
          {t("dashboard.queue.waiting.title")} · {items.length}
        </h2>
      </div>
      <ul className="pf-list">
        {items.map((row) => (
          <li key={row.id} className="pf-queue-row">
            <div className="pf-queue-body">
              <div className="pf-queue-title">
                <Link to={objectLink(row.object)}>{row.title}</Link>
              </div>
              <div className="pf-hint">{who(row, nowMs)}</div>
            </div>
            <Button
              aria-label={t("dashboard.queue.waiting.remindLabel", { title: row.title })}
              disabled={!canRemind(row, nowMs)}
              loading={remind.isPending && remind.variables.id === row.object_id}
              onClick={() => {
                remind.mutate({ kind: row.kind, id: row.object_id });
              }}
            >
              {t("dashboard.queue.waiting.remind")}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
