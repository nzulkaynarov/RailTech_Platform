import { Alert, Button, Card, Segmented, Skeleton } from "antd";
import { useCallback, useState } from "react";
import { useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";

import { canSee } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import {
  useGetProfile,
  useGetQueue,
  useGetQueueCards,
} from "../../shared/api/generated/platform-bff";
import type { Sources } from "../../shared/api/generated/model";
import { usePollQuery } from "../../shared/api/polling";
import { todayLabel } from "../../shared/lib/format";
import { useDocumentTitle } from "../../shared/lib/useDocumentTitle";
import { useFormat } from "../../shared/lib/useFormat";
import { CounterCard, CounterGrid, CounterGridSkeleton } from "../../shared/ui/CounterCard";
import { TelegramLinkButton } from "../../features/onboarding/TelegramLinkButton";
import { EmptyState } from "../../shared/ui/EmptyState";
import { LinkButton } from "../../shared/ui/LinkButton";
import { PageHeader } from "../../shared/ui/PageHeader";
import { SigningDecision } from "../eds/approvals/SigningDecision";

import "../eds/decision/decision.css";
import { bannerKind } from "../../shared/ui/bannerKind";
import { SourceBanner } from "../../shared/ui/SourceBanner";
import { matchSection } from "../registry";
import { isUrgent, pluralForm, queueEmptyKinds } from "./queue";
import { categoryOf, chipsOf, groupsOf } from "./queueModel";
import { QueueRow } from "./QueueRow";
import { WaitingBlock } from "./WaitingBlock";
import { useCardsCount } from "./useCardsCount";
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
  // EDS в ответе есть не всегда (только если его читали): пока ни один ответ о нём не сказал, поля нет
  const eds = known.some((s) => s.eds === "unavailable")
    ? "unavailable"
    : known.some((s) => s.eds === "ok")
      ? "ok"
      : undefined;
  return { crm: worst((s) => s.crm), erp: worst((s) => s.erp), ...(eds ? { eds } : {}) };
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
  const poll = usePollQuery();
  const queue = useGetQueue(undefined, { query: poll });
  const cards = useGetQueueCards(undefined, { query: poll });
  // Сколько счётчиков было в прошлый раз: до ответа — столько же карточек-скелетонов той же высоты (UX-1c, S10).
  const cardsCount = useCardsCount(me.id, cards.data?.cards.length);
  // Замещение (СЦ-9): «Вы замещаете {имя} до {дата}» и фильтр «За {имя}»; профиль не открылся — без плашки, очередь та же
  const profile = useGetProfile({ query: { staleTime: 60_000 } });
  const covering = profile.data?.covering ?? [];
  const [forId, setForId] = useState("all");
  const [search, setSearch] = useSearchParams();
  const focusSigning = search.get("signing");
  const [kind, setKind] = useState<string>("all");
  const closeSigning = useCallback(() => {
    setSearch(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("signing");
        return next;
      },
      { replace: true },
    );
  }, [setSearch]);
  const title = t("modules:dashboard.sections.queue");
  useDocumentTitle(title);

  const count = queue.data?.items.length;
  const overdueNow = groupsOf(queue.data?.items ?? [])
    .filter((block) => block.group === "overdue")
    .reduce((sum, block) => sum + block.items.length, 0);
  const subtitle = [
    todayLabel(i18n.language),
    count === undefined
      ? null
      : t(`modules:dashboard.queue.decisions.${pluralForm(i18n.language, count)}`, { count }),
    overdueNow > 0 ? t("modules:dashboard.queue.overdueCount", { count: overdueNow }) : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const allItems = queue.data?.items ?? [];
  const behalf = [
    ...new Map(
      allItems.flatMap((item) =>
        item.on_behalf_of ? [[item.on_behalf_of.id, item.on_behalf_of]] : [],
      ),
    ).values(),
  ];
  // Выбранного человека в очереди уже нет (шаг решили, замещение кончилось) — фильтр сам возвращается к «Все»
  const activeFor = behalf.some((person) => person.id === forId) ? forId : "all";
  const shown =
    activeFor === "all" ? allItems : allItems.filter((item) => item.on_behalf_of?.id === activeFor);
  // Фильтр по виду работы: чипы считают строки до фильтра «за {имя}»? Нет — по тому, что показано выбранным человеком
  const chips = chipsOf(shown);
  const activeKind = chips.some((chip) => chip.category === kind) ? kind : "all";
  const visible = activeKind === "all" ? shown : shown.filter((i) => categoryOf(i) === activeKind);
  const blocks = groupsOf(visible);
  // одна главная кнопка на экран: первая срочная строка (просрочено или сегодня)
  const primaryId = blocks.flatMap((block) => block.items).find((item) => isUrgent(item))?.id;

  const sources = mergeSources(queue.data?.sources, cards.data?.sources);
  const crmDown = sources?.crm === "unavailable";
  const erpDown = sources?.erp === "unavailable";
  const edsDown = sources?.eds === "unavailable";
  const partial = crmDown || erpDown || edsDown ? bannerKind(crmDown, erpDown, edsDown) : null;
  const names = {
    crm: t("modules:crm.name"),
    erp: t("modules:erp.name"),
    eds: t("modules:eds.name"),
  };
  const downNames = [crmDown && names.crm, erpDown && names.erp, edsDown && names.eds]
    .filter(Boolean)
    .map((name) => `«${String(name)}»`)
    .join(", ");
  const partialMessages = {
    crm: t("modules:dashboard.queue.partial.crm", names),
    erp: t("modules:dashboard.queue.partial.erp", names),
    eds: t("modules:dashboard.queue.partial.eds", names),
    both: t("modules:dashboard.queue.partial.both", names),
    multi: t("modules:dashboard.queue.partial.multi", { names: downNames }),
  };
  const emptyKinds = queueEmptyKinds(me);
  const [soleKind] = emptyKinds;
  const emptyKind = emptyKinds.length === 1 && soleKind ? soleKind : "default";
  // Несколько разделов (несколько ролей) — нейтральный заголовок и по тексту на каждый раздел
  const emptyText =
    emptyKinds.length === 1
      ? t(`modules:dashboard.queue.empty.${emptyKind}.text`)
      : emptyKinds.map((kind) => t(`modules:dashboard.queue.empty.${kind}.text`)).join(" ");

  const projects = matchSection("/eds/projects");
  const showLink = projects !== undefined && canSee(me, projects.section.access);
  const retry = () => {
    void queue.refetch();
    void cards.refetch();
  };

  let list;
  if (queue.isPending) {
    list = (
      <Card role="status" aria-busy="true" aria-label={t("modules:dashboard.queue.loading")}>
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
    const empty = partial ? (
      <EmptyState
        level={3}
        title={t("modules:dashboard.queue.partialEmpty.title")}
        text={t("modules:dashboard.queue.partialEmpty.text")}
      />
    ) : (
      <EmptyState
        level={3}
        title={t(`modules:dashboard.queue.empty.${emptyKind}.title`)}
        text={emptyText}
        action={
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
            {emptyKind === "director" && showLink ? (
              <LinkButton to="/eds/projects">
                {t("modules:dashboard.queue.empty.director.action")}
              </LinkButton>
            ) : null}
            <TelegramLinkButton />
          </div>
        }
      />
    );
    list = (
      <section className="pf-card pf-queue" aria-labelledby="pf-queue-title">
        <div className="pf-card-head">
          <h2 id="pf-queue-title" className="pf-card-title">
            {t("modules:dashboard.queue.title")}
          </h2>
        </div>
        {chips.length > 1 ? (
          <div
            className="pf-queue-chips"
            role="group"
            aria-label={t("modules:dashboard.queue.filterLabel")}
          >
            <button
              type="button"
              className="pf-queue-chip"
              aria-pressed={activeKind === "all"}
              onClick={() => {
                setKind("all");
              }}
            >
              {t("modules:dashboard.queue.filterAll")} <span>{shown.length}</span>
            </button>
            {chips.map((chip) => (
              <button
                key={chip.category}
                type="button"
                className="pf-queue-chip"
                aria-pressed={activeKind === chip.category}
                onClick={() => {
                  setKind(chip.category);
                }}
              >
                {t(`modules:dashboard.queue.categories.${chip.category}`)} <span>{chip.count}</span>
              </button>
            ))}
          </div>
        ) : null}
        {queue.data.truncated ? (
          <p className="pf-hint pf-queue-truncated" role="note">
            {t("modules:dashboard.queue.truncated")}
          </p>
        ) : null}
        {blocks.length === 0
          ? empty
          : blocks.map((block) => (
              <div key={block.group} className="pf-queue-group">
                <h3 className="pf-queue-group-title">
                  {t(`modules:dashboard.queue.groups.${block.group}`)} · {block.items.length}
                </h3>
                <ul className="pf-list">
                  {block.items.map((item) => (
                    <QueueRow key={item.id} item={item} primary={item.id === primaryId} />
                  ))}
                </ul>
              </div>
            ))}
      </section>
    );
  }

  return (
    <div className="pf-queue-page">
      <PageHeader title={title} subtitle={subtitle} />
      <SourceBanner sources={sources} onRetry={retry} messages={partialMessages} />
      {covering.map((person) => (
        <Alert
          key={person.user_id}
          type="info"
          showIcon
          message={t("modules:dashboard.queue.covering.banner", {
            name: person.name,
            date: format.date(person.date_to, "short"),
          })}
        />
      ))}
      {cards.isPending && cardsCount > 0 ? (
        <CounterGridSkeleton count={cardsCount} />
      ) : cards.data && cards.data.cards.length > 0 ? (
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
      {behalf.length > 0 ? (
        <Segmented
          aria-label={t("modules:dashboard.queue.covering.filterLabel")}
          value={activeFor}
          options={[
            { value: "all", label: t("modules:dashboard.queue.covering.filterAll") },
            ...behalf.map((person) => ({
              value: person.id,
              label: t("modules:dashboard.queue.covering.filterFor", { name: person.name }),
            })),
          ]}
          onChange={(value) => {
            setForId(value);
          }}
        />
      ) : null}
      {list}
      {!queue.isPending ? <WaitingBlock /> : null}
      {/* Подпись и виза документа ERP (SIGN-4): строка очереди ведёт сюда, решение — в окне */}
      <SigningDecision id={focusSigning} onClose={closeSigning} />
    </div>
  );
}
