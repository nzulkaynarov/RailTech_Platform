import { Button, Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";

import { canSee } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { useGetQueue, useGetQueueCards } from "../../shared/api/generated/platform-bff";
import type { Sources } from "../../shared/api/generated/model";
import { pollQuery } from "../../shared/api/polling";
import { todayLabel } from "../../shared/lib/format";
import { useDocumentTitle } from "../../shared/lib/useDocumentTitle";
import { useFormat } from "../../shared/lib/useFormat";
import { CounterCard, CounterGrid } from "../../shared/ui/CounterCard";
import { EmptyState } from "../../shared/ui/EmptyState";
import { LinkButton } from "../../shared/ui/LinkButton";
import { PageHeader } from "../../shared/ui/PageHeader";
import { QueueList, type QueueItem as RowItem } from "../../shared/ui/QueueList";
import { SourceBanner } from "../../shared/ui/SourceBanner";
import { matchSection } from "../registry";
import { dueBadge, pluralForm } from "./queue";
import "./dashboard.css";

/** Плашка нужна, если хотя бы в одном из ответов источник не ответил. */
function mergeSources(...all: (Sources | undefined)[]): Sources | undefined {
  const known = all.filter((s): s is Sources => s !== undefined);
  if (known.length === 0) return undefined;
  const worst = (pick: (s: Sources) => Sources["crm"]) =>
    known.some((s) => pick(s) === "unavailable")
      ? "unavailable"
      : known.every((s) => pick(s) === "not_applicable")
        ? "not_applicable"
        : "ok";
  return { crm: worst((s) => s.crm), erp: worst((s) => s.erp) };
}

/**
 * Dashboard · Моя очередь (SPEC-v3 §7.1, макет «v3 · 1. Dashboard»): заголовок с ролью, датой и числом решений,
 * счётчики-карточки (набор задаёт роль), «Что сделать сейчас». Данные — BFF, опрос 30 с и при фокусе; очередь и карточки
 * считаются по активной роли, если она выбрана (Q-PLT-12-1).
 */
export function QueuePage() {
  const { me } = useAuth();
  const { t, i18n } = useTranslation(["modules", "shell"]);
  const format = useFormat();
  const role = me.active_role ?? undefined;
  const params = role ? { role } : undefined;
  const queue = useGetQueue(params, { query: pollQuery });
  const cards = useGetQueueCards(params, { query: pollQuery });
  const title = t("modules:dashboard.sections.queue");
  useDocumentTitle(title);

  const roles =
    !me.active_role && me.roles.length > 1
      ? [t("shell:avatar.allRoles")]
      : (me.active_role ? [me.active_role] : me.roles).map((r) => t(`shell:roles.${r}`));
  const count = queue.data?.items.length;
  const subtitle = [
    roles.join(", "),
    todayLabel(i18n.language),
    count === undefined
      ? null
      : t(`modules:dashboard.queue.decisions.${pluralForm(i18n.language, count)}`, { count }),
  ]
    .filter(Boolean)
    .join(" · ");

  const rows: RowItem[] = (queue.data?.items ?? []).map((item) => ({
    id: item.id,
    badge: dueBadge(
      item,
      (key, options) => t(key, options),
      (value) => format.date(value, "short"),
    ),
    title: item.title,
    caption: item.subtitle,
    to: item.object.path,
  }));

  const projects = matchSection("/dashboard/projects");
  const showLink = projects !== undefined && canSee(me, projects.section.access);
  const retry = () => {
    void queue.refetch();
    void cards.refetch();
  };

  let list;
  if (queue.isPending) {
    list = (
      <Card aria-busy="true" aria-label={t("modules:dashboard.queue.loading")}>
        <Skeleton active paragraph={{ rows: 3 }} />
      </Card>
    );
  } else if (queue.isError) {
    list = (
      <Card>
        <EmptyState
          title={t("modules:dashboard.queue.loadErrorTitle")}
          text={t("modules:dashboard.queue.loadErrorText")}
          action={<Button onClick={retry}>{t("modules:dashboard.queue.retry")}</Button>}
        />
      </Card>
    );
  } else {
    list = (
      <QueueList
        title={t("modules:dashboard.queue.title")}
        items={rows}
        empty={
          <EmptyState
            level={3}
            title={t("modules:dashboard.stub.queue.title")}
            text={t("modules:dashboard.stub.queue.text")}
            action={
              showLink ? (
                <LinkButton to="/dashboard/projects">
                  {t("modules:dashboard.stub.queue.action")}
                </LinkButton>
              ) : undefined
            }
          />
        }
      />
    );
  }

  return (
    <div className="pf-queue-page">
      <PageHeader title={title} subtitle={subtitle} />
      <SourceBanner
        sources={mergeSources(queue.data?.sources, cards.data?.sources)}
        onRetry={retry}
      />
      {cards.data && cards.data.cards.length > 0 ? (
        <section aria-label={t("modules:dashboard.queue.cardsLabel")}>
          <CounterGrid>
            {cards.data.cards.map((card) => (
              <CounterCard
                key={card.key}
                label={card.label}
                value={card.count}
                source={card.hint}
                to={card.path}
              />
            ))}
          </CounterGrid>
        </section>
      ) : null}
      {list}
    </div>
  );
}
