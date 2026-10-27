import { Alert, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  BusDelivery,
  BusDomain,
  BusInboxEntry,
  BusRetryResult,
  BusSubscriber,
} from "../../../shared/api/generated/model";
import {
  useRetryBusDeadLetters,
  useRetryBusDelivery,
  useRetryBusInbox,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { StatusTag } from "../../../shared/ui/StatusTag";
import {
  DELIVERY_TONE,
  INBOX_TONE,
  busErrorText,
  deliveryWord,
  domainName,
  inboxWord,
  subscriberName,
  useRefreshBus,
} from "./format";

import "./bus.css";

function Outcome({ result, error }: { result: BusRetryResult | undefined; error: unknown }) {
  const { t } = useTranslation("bus");
  if (error) {
    return <Alert type="error" showIcon role="alert" message={busErrorText(t, error)} />;
  }
  if (!result) return null;
  return (
    <Alert
      type={result.retried > 0 ? "success" : "info"}
      showIcon
      role="status"
      message={t(result.retried > 0 ? "panel.retried" : "panel.nothing")}
    />
  );
}

/** Доставка в боковом окне: метаданные (без тела события) и «Повторить доставку» с «Что произойдёт». */
export function DeliveryPanel({ delivery }: { delivery: BusDelivery }) {
  const { t } = useTranslation("bus");
  const { date, number } = useFormat();
  const refresh = useRefreshBus();
  const retry = useRetryBusDelivery({ mutation: { onSuccess: refresh } });
  const word = deliveryWord(delivery);
  const retriable = delivery.status === "dead" || delivery.status === "pending";
  const domain = domainName(t, delivery.domain);
  return (
    <div className="pf-bus-panel">
      <h3 className="pf-bus-panel-title">
        {t("panel.deliveryTitle", { id: String(delivery.id), domain })}
      </h3>
      <StatusTag tone={DELIVERY_TONE[word]}>{t(`delivery.${word}`)}</StatusTag>
      <DefinitionList
        items={[
          { label: t("panel.fields.domain"), value: domain },
          { label: t("panel.fields.subscriber"), value: subscriberName(t, delivery.subscriber) },
          { label: t("panel.fields.event"), value: <code>{delivery.event_type}</code> },
          { label: t("panel.fields.eventId"), value: <code>{delivery.event_id}</code> },
          { label: t("panel.fields.subject"), value: delivery.subject },
          { label: t("panel.fields.correlation"), value: delivery.correlation_id },
          { label: t("panel.fields.attempts"), value: number(delivery.attempts) },
          {
            label: t("panel.fields.lastAttempt"),
            value: delivery.last_attempt_at ? date(delivery.last_attempt_at, "datetime") : null,
          },
          {
            label: t("panel.fields.nextAttempt"),
            value: delivery.next_attempt_at ? date(delivery.next_attempt_at, "datetime") : null,
          },
          {
            label: t("panel.fields.code"),
            value: delivery.last_status_code === null ? null : String(delivery.last_status_code),
          },
          {
            label: t("panel.fields.error"),
            value: delivery.last_error ? (
              <span className="pf-bus-break">{delivery.last_error}</span>
            ) : null,
          },
          { label: t("panel.fields.created"), value: date(delivery.created_at, "datetime") },
          {
            label: t("panel.fields.delivered"),
            value: delivery.delivered_at ? date(delivery.delivered_at, "datetime") : null,
          },
        ]}
      />
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("panel.noBody")}
      </p>
      {retriable ? (
        <div className="pf-bus-action">
          <Consequence
            items={[
              t("panel.consequence.now"),
              t("panel.consequence.probe"),
              t("panel.consequence.safe"),
            ]}
          />
          <Button
            type="primary"
            loading={retry.isPending}
            aria-label={t("panel.retryDeliveryAria", { id: String(delivery.id) })}
            onClick={() => {
              retry.mutate({ domain: delivery.domain, id: delivery.id });
            }}
          >
            {t("panel.retryDelivery")}
          </Button>
          <Outcome result={retry.data} error={retry.error} />
        </div>
      ) : (
        <p className="pf-bus-muted">{t("panel.notRetriable")}</p>
      )}
    </div>
  );
}

/** Принятое событие в боковом окне: метаданные и «Повторить обработку» (для `failed` и `skipped`). */
export function InboxPanel({ entry }: { entry: BusInboxEntry }) {
  const { t } = useTranslation("bus");
  const { date, number } = useFormat();
  const refresh = useRefreshBus();
  const retry = useRetryBusInbox({ mutation: { onSuccess: refresh } });
  const word = inboxWord(entry);
  const retriable = entry.status === "failed" || entry.status === "skipped";
  const domain = domainName(t, entry.domain);
  return (
    <div className="pf-bus-panel">
      <h3 className="pf-bus-panel-title">{t("panel.inboxTitle", { domain })}</h3>
      <StatusTag tone={INBOX_TONE[word]}>{t(`inbox.${word}`)}</StatusTag>
      <DefinitionList
        items={[
          { label: t("panel.fields.receiver"), value: domain },
          { label: t("panel.fields.publisher"), value: subscriberName(t, entry.publisher) },
          { label: t("panel.fields.event"), value: <code>{entry.type}</code> },
          { label: t("panel.fields.eventId"), value: <code>{entry.event_id}</code> },
          { label: t("panel.fields.subject"), value: entry.subject },
          { label: t("panel.fields.correlation"), value: entry.correlation_id },
          { label: t("panel.fields.attempts"), value: number(entry.attempts) },
          {
            label: t("panel.fields.error"),
            value: entry.error ? <span className="pf-bus-break">{entry.error}</span> : null,
          },
          { label: t("panel.fields.received"), value: date(entry.received_at, "datetime") },
          {
            label: t("panel.fields.processed"),
            value: entry.processed_at ? date(entry.processed_at, "datetime") : null,
          },
        ]}
      />
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("panel.noBody")}
      </p>
      {retriable ? (
        <div className="pf-bus-action">
          <Consequence
            items={[
              t("panel.consequence.inboxNow", { domain }),
              t("panel.consequence.inboxFix"),
              t("panel.consequence.inboxSafe"),
            ]}
          />
          <Button
            type="primary"
            loading={retry.isPending}
            onClick={() => {
              retry.mutate({ domain: entry.domain, eventId: entry.event_id });
            }}
          >
            {t("panel.retryInbox")}
          </Button>
          <Outcome result={retry.data} error={retry.error} />
        </div>
      ) : (
        <p className="pf-bus-muted">{t("panel.inboxNotRetriable")}</p>
      )}
    </div>
  );
}

/** «Повторить все dead подписчика»: опасное массовое действие — «Что произойдёт» и одна главная кнопка. */
export function RetryDeadPanel({
  domain,
  subscriber,
}: {
  domain: BusDomain;
  subscriber: BusSubscriber;
}) {
  const { t } = useTranslation("bus");
  const refresh = useRefreshBus();
  const [done, setDone] = useState<number | null>(null);
  const retry = useRetryBusDeadLetters({
    mutation: {
      onSuccess: (result) => {
        setDone(result.retried);
        refresh();
      },
    },
  });
  const name = subscriberName(t, subscriber.name);
  const publisher = domainName(t, domain);
  const count = subscriber.dead;
  return (
    <div className="pf-bus-panel">
      <h3 className="pf-bus-panel-title">{t("panel.deadTitle", { subscriber: name })}</h3>
      <p className="pf-bus-muted">
        {t("panel.deadIntro", { domain: publisher, subscriber: name, count })}
      </p>
      {done === null ? (
        <div className="pf-bus-action">
          <Consequence
            items={[
              t("panel.deadConsequence.now", { count }),
              t("panel.deadConsequence.fix"),
              t("panel.deadConsequence.probe"),
              t("panel.deadConsequence.safe", { domain: publisher }),
            ]}
          />
          <Button
            type="primary"
            danger
            loading={retry.isPending}
            onClick={() => {
              retry.mutate({ domain, data: { subscriber: subscriber.name } });
            }}
          >
            {t("panel.deadSubmit", { count })}
          </Button>
          {retry.error ? (
            <Alert type="error" showIcon role="alert" message={busErrorText(t, retry.error)} />
          ) : null}
        </div>
      ) : (
        <Alert
          type={done > 0 ? "success" : "info"}
          showIcon
          role="status"
          message={done > 0 ? t("panel.deadDone", { count: done }) : t("panel.deadNone")}
        />
      )}
    </div>
  );
}
