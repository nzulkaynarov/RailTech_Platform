import { Alert, App, Button, Progress, Select } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ImapHistory, ImapHistoryInDays } from "../../../shared/api/generated/model";
import {
  getGetImapConnectorQueryKey,
  useStartImapHistory,
} from "../../../shared/api/generated/platform-bff";
import { ErrorNote, Field } from "./parts";

const PERIODS = [7, 14, 30, 90] as const satisfies readonly ImapHistoryInDays[];

function HistoryState({
  history,
  reason,
}: {
  history: ImapHistory;
  reason: (k: string) => string;
}) {
  const { t } = useTranslation("integrations");
  if (history.status === "running") {
    if (history.found === 0) {
      return (
        <p className="pf-hint" role="status" style={{ margin: 0 }}>
          {t("mail.inbound.history.searching")}
        </p>
      );
    }
    const text = t("mail.inbound.history.running", {
      processed: history.processed,
      found: history.found,
    });
    return (
      <div role="status" aria-label={text}>
        <Progress
          percent={Math.round((history.processed / Math.max(history.found, 1)) * 100)}
          size="small"
        />
        <p className="pf-hint" style={{ margin: 0 }}>
          {text}
        </p>
      </div>
    );
  }
  if (history.status === "error") {
    return (
      <Alert
        type="error"
        showIcon
        role="status"
        message={t("mail.inbound.history.error", {
          reason: reason(history.error_kind ?? "unavailable"),
        })}
      />
    );
  }
  return (
    <>
      <Alert
        type="success"
        showIcon
        role="status"
        message={t("mail.inbound.history.done", {
          created: history.created,
          found: history.found,
        })}
        description={t("mail.inbound.history.again")}
      />
      {history.limited ? (
        <Alert type="warning" showIcon message={t("mail.inbound.history.limited")} />
      ) : null}
    </>
  );
}

/**
 * «Загрузить письма за период» (W18A-P2-2; эталон — импорт истории в Front и Help Scout): одно действие, фоном; ход —
 * опросом настроек раз в 2 секунды, итог «загружено N». Повтор безопасен: дубль по Message-ID не создаётся.
 */
export function InboundHistory({
  history,
  reason,
}: {
  history: ImapHistory | null;
  reason: (kind: string) => string;
}) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const client = useQueryClient();
  const [days, setDays] = useState<ImapHistoryInDays>(30);
  const start = useStartImapHistory({
    mutation: {
      onSuccess: () => {
        void client.invalidateQueries({ queryKey: getGetImapConnectorQueryKey() });
        void message.info(t("mail.inbound.history.searching"));
      },
    },
  });
  const running = history?.status === "running";
  return (
    <section className="pf-panel-stack" aria-labelledby="imap-history-title">
      <h5 id="imap-history-title" className="pf-int-subhead">
        {t("mail.inbound.history.title")}
      </h5>
      <div className="pf-int-row">
        <Field id="imap-history-days" label={t("mail.inbound.history.period")}>
          <Select<ImapHistoryInDays>
            id="imap-history-days"
            value={days}
            style={{ minWidth: 140 }}
            disabled={running}
            options={PERIODS.map((value) => ({
              value,
              label: t("mail.inbound.history.days", { count: value }),
            }))}
            onChange={setDays}
          />
        </Field>
        <Button
          loading={start.isPending}
          disabled={running}
          onClick={() => {
            start.mutate({ data: { days } });
          }}
        >
          {t("mail.inbound.history.button")}
        </Button>
      </div>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("mail.inbound.history.hint")}
      </p>
      {history ? <HistoryState history={history} reason={reason} /> : null}
      <ErrorNote error={start.error} />
    </section>
  );
}
