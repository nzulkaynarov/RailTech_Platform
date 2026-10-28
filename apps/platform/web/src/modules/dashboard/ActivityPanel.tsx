import { Button, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { NotificationCenter } from "../../features/notifications/NotificationCenter";
import type { ActivityItem } from "../../shared/api/generated/model";
import { useGetActivityToday } from "../../shared/api/generated/platform-bff";
import { usePollQuery } from "../../shared/api/polling";
import { type StatusTone, TONE_STYLE } from "../../shared/lib/statuses";
import { useFormat } from "../../shared/lib/useFormat";
import { EmptyState } from "../../shared/ui/EmptyState";
import { SourceBanner } from "../../shared/ui/SourceBanner";
import { objectLink } from "../objectLinks";
import { moduleName } from "../registry";
import "../../features/notifications/notifications.css";

const AVATAR_TONES: readonly StatusTone[] = ["blue", "gold", "cyan", "purple"];

/** Цвет аватара — по имени сотрудника: один человек всегда одного цвета. */
function toneOf(name: string): StatusTone {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + (char.codePointAt(0) ?? 0)) % 997;
  return AVATAR_TONES[hash % AVATAR_TONES.length] ?? "blue";
}

function Row({ item }: { item: ActivityItem }) {
  const format = useFormat();
  const { t } = useTranslation("modules");
  const module = moduleName(t, item.module);
  // Административные события ERP BFF присылает кодом: фраза — на языке сотрудника, а не готовой русской строкой.
  const text =
    item.code && !item.object
      ? t(`modules:dashboard.activity.events.${item.code}`, { defaultValue: item.text })
      : item.text;
  const hint = [module, item.object?.number, format.activity(item.at)].filter(Boolean).join(" · ");
  const body = (
    <>
      <span className="pf-chip" style={TONE_STYLE[toneOf(item.actor.name)]} aria-hidden="true">
        {item.actor.initials}
      </span>
      <span style={{ minWidth: 0 }}>
        <span style={{ display: "block" }}>
          <b style={{ fontWeight: 500 }}>{item.actor.name}</b>{" "}
          <span style={{ color: "#595959" }}>{text}</span>
        </span>
        <span className="pf-hint" style={{ display: "block" }}>
          {hint}
        </span>
      </span>
    </>
  );
  return (
    <li>
      {item.object ? (
        <Link to={objectLink(item.object)} className="pf-feed-row">
          {body}
        </Link>
      ) : (
        <div className="pf-feed-row">{body}</div>
      )}
    </li>
  );
}

/** Вкладка «Сегодня» бокового окна Dashboard (SPEC-v3 §7.1): лента событий компании за день, 4–8 записей. */
export function TodayTab() {
  const { t } = useTranslation(["modules"]);
  const poll = usePollQuery();
  const query = useGetActivityToday({ query: poll });
  const retry = () => {
    void query.refetch();
  };

  if (query.isPending) {
    return (
      <div role="status" aria-label={t("modules:dashboard.activity.loading")}>
        <Skeleton active paragraph={{ rows: 4 }} title={false} />
      </div>
    );
  }
  if (query.isError) {
    return (
      <EmptyState
        level={3}
        compact
        title={t("modules:dashboard.activity.loadErrorTitle")}
        text={t("modules:dashboard.activity.loadErrorText")}
        action={<Button onClick={retry}>{t("modules:dashboard.queue.retry")}</Button>}
      />
    );
  }
  return (
    <>
      <SourceBanner sources={query.data.sources} onRetry={retry} />
      {query.data.items.length === 0 ? (
        <EmptyState
          level={3}
          compact
          title={t("modules:panel.today.title")}
          text={t("modules:panel.today.text")}
        />
      ) : (
        <ul className="pf-feed" aria-label={t("modules:dashboard.activity.label")}>
          {query.data.items.map((item) => (
            <Row key={item.id} item={item} />
          ))}
        </ul>
      )}
    </>
  );
}

/** Вкладка «Уведомления» бокового окна Dashboard: тот же список, что в колокольчике, без вкладок. */
export function NotificationsTab() {
  return <NotificationCenter variant="panel" />;
}
