import { Button, Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";

import { canSee } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { useGetQueue, useGetQueueCards } from "../../shared/api/generated/platform-bff";
import type { Sources } from "../../shared/api/generated/model";
import { usePollQuery } from "../../shared/api/polling";
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
import { viewRoleNames } from "../../entities/role/roles";
import { isActionable } from "../bridge";
import { WhereToDo } from "../stub/WhereToDo";
import { dueBadge, isUrgent, pluralForm, queueEmptyKind } from "./queue";
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
 * Главная · Мои задачи (SPEC-v3 §7.1, макет «v3 · 1. Dashboard»): заголовок с ролью, датой и числом решений,
 * счётчики-карточки (набор задаёт роль), «Что сделать сейчас». Данные — BFF, опрос 30 с и при фокусе; очередь и карточки
 * считаются по активной роли, если она выбрана (Q-PLT-12-1).
 */
export function QueuePage() {
  const { me } = useAuth();
  const { t, i18n } = useTranslation(["modules", "shell"]);
  const format = useFormat();
  const role = me.active_role ?? undefined;
  const params = role ? { role } : undefined;
  const poll = usePollQuery();
  const queue = useGetQueue(params, { query: poll });
  const cards = useGetQueueCards(params, { query: poll });
  const title = t("modules:dashboard.sections.queue");
  useDocumentTitle(title);

  const roles = viewRoleNames(me, t("shell:avatar.allRoles"));
  const count = queue.data?.items.length;
  const subtitle = [
    roles,
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
    // Строка замещаемого коллеги (W15-H6): «за Имя · …» — чья это работа.
    caption: item.on_behalf_of
      ? `${t("modules:dashboard.queue.onBehalf", { name: item.on_behalf_of.name })} · ${item.subtitle}`
      : item.subtitle,
    to: item.object.path,
    urgent: isUrgent(item),
    // У цели нет экрана в Платформе — «Где сделать» вместо ссылки на заглушку (W15-H2).
    ...(isActionable(item.object.path) ? {} : { where: <WhereToDo path={item.object.path} /> }),
  }));

  const sources = mergeSources(queue.data?.sources, cards.data?.sources);
  const partial =
    sources?.crm === "unavailable" && sources.erp === "unavailable"
      ? "both"
      : sources?.crm === "unavailable"
        ? "crm"
        : sources?.erp === "unavailable"
          ? "erp"
          : null;
  const names = {
    crm: t("modules:crm.name"),
    eds: t("modules:eds.name"),
    erp: t("modules:erp.name"),
  };
  const partialMessages = {
    crm: t("modules:dashboard.queue.partial.crm", names),
    erp: t("modules:dashboard.queue.partial.erp", names),
    both: t("modules:dashboard.queue.partial.both", names),
  };
  const emptyKind = queueEmptyKind(me);

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
          partial ? (
            <EmptyState
              level={3}
              title={t("modules:dashboard.queue.partialEmpty.title")}
              text={t("modules:dashboard.queue.partialEmpty.text")}
            />
          ) : (
            <EmptyState
              level={3}
              title={t(`modules:dashboard.queue.empty.${emptyKind}.title`)}
              text={t(`modules:dashboard.queue.empty.${emptyKind}.text`)}
              action={
                emptyKind === "director" && showLink ? (
                  <LinkButton to="/dashboard/projects">
                    {t("modules:dashboard.queue.empty.director.action")}
                  </LinkButton>
                ) : undefined
              }
            />
          )
        }
      />
    );
  }

  return (
    <div className="pf-queue-page">
      <PageHeader title={title} subtitle={subtitle} />
      <SourceBanner sources={sources} onRetry={retry} messages={partialMessages} />
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
