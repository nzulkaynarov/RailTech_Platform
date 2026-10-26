import { Button, Card, Table } from "antd";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import type {
  BusDomain,
  BusDomainOverview,
  BusSubscriber,
} from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { STATE_TONE, ageText, domainName, subscriberName } from "./format";
import { ScrollRegion } from "./parts";

export interface SubscribersViewProps {
  domains: readonly BusDomainOverview[];
  selected: { domain: BusDomain; name: string } | null;
  onRetryDead: (domain: BusDomain, subscriber: BusSubscriber) => void;
}

function StateCell({ subscriber }: { subscriber: BusSubscriber }) {
  const { t } = useTranslation("bus");
  const { date } = useFormat();
  return (
    <span className="pf-bus-state">
      <StatusTag tone={STATE_TONE[subscriber.state]}>{t(`state.${subscriber.state}`)}</StatusTag>
      {subscriber.state === "paused" && subscriber.paused_until ? (
        <span className="pf-hint">
          {t("subscribers.pausedUntil", { time: date(subscriber.paused_until, "time") })}
        </span>
      ) : null}
    </span>
  );
}

/** Последняя ошибка; ошибки подряд (до паузы предохранителя) — числом впереди. */
function ErrorCell({ subscriber }: { subscriber: BusSubscriber }) {
  const { t } = useTranslation("bus");
  if (!subscriber.last_error) {
    return <span className="pf-hint">{t("subscribers.noErrors")}</span>;
  }
  return (
    <span className="pf-bus-error" title={subscriber.last_error}>
      {subscriber.consecutive_failures > 0
        ? `${t("subscribers.inARow", { n: subscriber.consecutive_failures })} · `
        : ""}
      {subscriber.last_error}
    </span>
  );
}

function RetryDeadButton({
  domain,
  subscriber,
  onRetryDead,
  short = false,
}: {
  domain: BusDomain;
  subscriber: BusSubscriber;
  onRetryDead: SubscribersViewProps["onRetryDead"];
  /** В таблице — «Повторить» рядом с числом DLQ; в списке на телефоне — «Повторить все dead». */
  short?: boolean;
}) {
  const { t } = useTranslation("bus");
  if (subscriber.dead === 0) return null;
  return (
    <Button
      size="small"
      aria-label={t("subscribers.retryDeadAria", {
        subscriber: subscriberName(t, subscriber.name),
        domain: domainName(t, domain),
      })}
      onClick={() => {
        onRetryDead(domain, subscriber);
      }}
    >
      {t(short ? "subscribers.retry" : "subscribers.retryDead")}
    </Button>
  );
}

function SubscriberName({ subscriber }: { subscriber: BusSubscriber }) {
  const { t } = useTranslation("bus");
  return (
    <div className="pf-bus-cell-stack">
      <span className="pf-bus-strong">{subscriberName(t, subscriber.name)}</span>
      <span className="pf-hint pf-bus-ellipsis" title={subscriber.endpoint ?? undefined}>
        {subscriber.endpoint ?? t("subscribers.noEndpoint")}
      </span>
    </div>
  );
}

function DomainCard({
  overview,
  selected,
  onRetryDead,
  compact,
}: {
  overview: BusDomainOverview;
  selected: SubscribersViewProps["selected"];
  onRetryDead: SubscribersViewProps["onRetryDead"];
  compact: boolean;
}) {
  const { t } = useTranslation("bus");
  const { number } = useFormat();
  const domain = domainName(t, overview.domain);
  const titleId = `pf-bus-domain-${overview.domain}`;
  const caption = t("subscribers.caption", { domain });
  const isSelected = (s: BusSubscriber) =>
    selected?.domain === overview.domain && selected.name === s.name;

  let body;
  if (overview.subscribers.length === 0) {
    body = <p className="pf-bus-empty">{t("subscribers.empty", { domain })}</p>;
  } else if (compact) {
    body = (
      <ul className="pf-bus-list" aria-label={caption}>
        {overview.subscribers.map((s) => (
          <li key={s.name} data-selected={isSelected(s)}>
            <div className="pf-bus-list-head">
              <span className="pf-bus-strong">{subscriberName(t, s.name)}</span>
              <StateCell subscriber={s} />
            </div>
            <span className="pf-hint">
              {t("subscribers.summary", {
                pending: number(s.pending),
                dead: number(s.dead),
                oldest: ageText(t, s.oldest_undelivered_age_seconds) ?? "—",
              })}
            </span>
            <ErrorCell subscriber={s} />
            <RetryDeadButton domain={overview.domain} subscriber={s} onRetryDead={onRetryDead} />
          </li>
        ))}
      </ul>
    );
  } else {
    body = (
      <ScrollRegion label={caption}>
        <Table<BusSubscriber>
          rowKey="name"
          dataSource={[...overview.subscribers]}
          pagination={false}
          size="middle"
          aria-labelledby={titleId}
          rowClassName={(s) => (isSelected(s) ? "pf-bus-row-selected" : "")}
          columns={[
            {
              title: t("subscribers.columns.subscriber"),
              key: "name",
              width: 200,
              render: (_, s) => <SubscriberName subscriber={s} />,
            },
            {
              title: t("subscribers.columns.state"),
              key: "state",
              render: (_, s) => <StateCell subscriber={s} />,
            },
            {
              title: t("subscribers.columns.queue"),
              key: "queue",
              align: "right",
              render: (_, s) => (
                <div className="pf-bus-cell-stack">
                  <span className="pf-num">{number(s.pending)}</span>
                  {s.in_flight > 0 ? (
                    <span className="pf-hint">{t("subscribers.inFlight", { n: s.in_flight })}</span>
                  ) : null}
                </div>
              ),
            },
            {
              title: t("subscribers.columns.dead"),
              key: "dead",
              align: "right",
              render: (_, s) => (
                <span className="pf-bus-dead">
                  <span className="pf-num">{number(s.dead)}</span>
                  <RetryDeadButton
                    domain={overview.domain}
                    subscriber={s}
                    onRetryDead={onRetryDead}
                    short
                  />
                </span>
              ),
            },
            {
              title: t("subscribers.columns.oldest"),
              key: "oldest",
              render: (_, s) => (
                <span className="pf-num">
                  {ageText(t, s.oldest_undelivered_age_seconds) ?? "—"}
                </span>
              ),
            },
            {
              title: t("subscribers.columns.lastError"),
              key: "error",
              render: (_, s) => <ErrorCell subscriber={s} />,
            },
          ]}
        />
      </ScrollRegion>
    );
  }

  return (
    <section aria-labelledby={titleId}>
      <Card
        styles={{ body: { padding: 0 } }}
        title={
          <h3 className="pf-bus-card-title" id={titleId}>
            {t("subscribers.title", { domain })}
          </h3>
        }
      >
        {body}
      </Card>
    </section>
  );
}

/** Подписчики по доменам-издателям: состояние словом, предохранитель, очередь, DLQ и «Повторить все dead». */
export function SubscribersView({ domains, selected, onRetryDead }: SubscribersViewProps) {
  const { mobile } = useViewport();
  return (
    <div className="pf-bus-stack">
      {domains.map((overview) => (
        <DomainCard
          key={overview.domain}
          overview={overview}
          selected={selected}
          onRetryDead={onRetryDead}
          compact={mobile}
        />
      ))}
    </div>
  );
}
