import { Alert, Button, Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import type {
  AttentionItem,
  IntegrationCard,
  IntegrationCardKey,
} from "../../../shared/api/generated/model";
import { useGetIntegrationsOverview } from "../../../shared/api/generated/platform-bff";
import { WIZARD_PATH } from "../../../entities/setup/steps";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusStrip } from "../../../shared/ui/StatusStrip";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { AttentionGroupRow } from "./AttentionGroup";
import { mergeSameCause } from "./attention";
import { attentionTexts } from "./attentionTexts";
import { CabinetAddress } from "./CabinetAddress";
import { TechnicalDetails } from "./HealthParts";
import { ErpPanel } from "./ErpPanel";
import { ModelsPanel } from "./ModelsPanel";
import { type CheckOutcome, useCardCheck } from "./useCardCheck";
import { ServicesPanel } from "./ServicesPanel";
import { StoragePanel } from "./StoragePanel";
import { SystemPanel } from "./SystemPanel";
import { PageFrame } from "../../../shared/ui/PageFrame";

import "./integrations.css";

const PATH = "/admin/integrations";
const CARD_KEYS: readonly IntegrationCardKey[] = [
  "erp",
  "telegram",
  "mail",
  "services",
  "models",
  "spend",
  "storage",
  "system",
];

/** Карточки, у которых своя страница Настроек (SET-IA): «Открыть» ведёт туда, а не в боковое окно. */
const OWN_PAGE: Partial<Record<IntegrationCardKey, string>> = {
  telegram: "/admin/telegram",
  mail: "/admin/mail",
  spend: "/admin/ai-spend",
};

function cardHref(key: IntegrationCardKey): string {
  return OWN_PAGE[key] ?? `${PATH}?card=${key}&panel=open`;
}

function isCardKey(value: string | null): value is IntegrationCardKey {
  return value !== null && (CARD_KEYS as readonly string[]).includes(value);
}

function noteText(t: ReturnType<typeof useTranslation>["t"], card: IntegrationCard): string {
  if (card.access === "forbidden") return t("access.forbidden");
  if (card.access === "unavailable") return t("access.unavailable");
  // «Всё в порядке» — только у слова «Работает» (аудит Настроек §6.2): BFF уже не шлёт его иначе, экран не доверяет слепо.
  const note = card.note === "all_ok" && card.fact.state !== "works" ? "no_data" : card.note;
  return t(`notes.${note}`, { count: card.count ?? 0 });
}

function IntegrationTile({
  card,
  selected,
  editable,
  running,
  outcome,
  onCheck,
}: {
  card: IntegrationCard;
  selected: boolean;
  editable: boolean;
  running: boolean;
  outcome: CheckOutcome | undefined;
  onCheck: () => void;
}) {
  const { t } = useTranslation("integrations");
  const { money } = useFormat();
  const title = t(`cards.${card.key}.title`);
  const isReport = card.key === "spend" || card.key === "system";
  const usd = (value: number) => money(value, { currency: "USD", fractionDigits: 2 });
  return (
    <article
      className="pf-int-card"
      data-selected={selected}
      data-card={card.key}
      aria-labelledby={`pf-int-${card.key}`}
    >
      <div className="pf-int-card-head">
        <h3 className="pf-int-card-title" id={`pf-int-${card.key}`}>
          {title}
        </h3>
      </div>
      <p className="pf-int-card-purpose">{t(`cards.${card.key}.purpose`)}</p>
      <p className="pf-int-card-note">{noteText(t, card)}</p>
      {card.key === "spend" && card.amount_usd !== null && card.access === "ok" ? (
        <p className="pf-int-card-note">{t("spendToday", { amount: usd(card.amount_usd) })}</p>
      ) : null}
      {card.access !== "forbidden" ? (
        <StatusStrip
          fact={card.fact}
          scope={t(`cards.${card.key}.scope`)}
          {...(editable || isReport
            ? {
                onCheck,
                checking: running,
                checkAria: t(isReport ? "refreshAria" : "checkAria", { title }),
                ...(isReport ? { checkLabel: t("common.refresh") } : {}),
              }
            : {})}
        />
      ) : null}
      {outcome ? (
        <Alert
          type={
            outcome.state === "error" ? "error" : outcome.state === "works" ? "success" : "warning"
          }
          showIcon
          role={outcome.state === "error" ? "alert" : "status"}
          message={outcome.text}
        />
      ) : null}
      <div className="pf-int-card-foot">
        <LinkButton
          to={cardHref(card.key)}
          aria-label={t("openAria", { title })}
          aria-current={selected ? "true" : undefined}
        >
          {t("open")}
        </LinkButton>
      </div>
    </article>
  );
}

function AttentionSection({
  items,
  cards,
  editable,
}: {
  items: readonly AttentionItem[];
  cards: readonly IntegrationCard[];
  editable: boolean;
}) {
  const { t } = useTranslation("integrations");
  // «Всё в порядке» — только когда каждая карточка живая и свежая; иначе называем, что не проверено (как «Состояние»)
  const unchecked = cards.filter(
    (card) =>
      card.access !== "forbidden" && card.fact.state !== "works" && card.fact.state !== "off",
  );
  return (
    <section aria-labelledby="pf-int-attention">
      <Card
        styles={{ body: { padding: 0 } }}
        title={
          <h2 className="pf-int-section-title" id="pf-int-attention">
            {t("attention.title")}
          </h2>
        }
      >
        {items.length === 0 ? (
          <p className="pf-int-empty">
            {unchecked.length === 0
              ? t("attention.empty")
              : t("attention.emptyUnverified", {
                  list: unchecked.map((card) => t(`cards.${card.key}.title`)).join(", "),
                })}
          </p>
        ) : (
          <ul className="pf-int-attention">
            {mergeSameCause(items).map((item) => {
              if (item.group !== null) {
                return (
                  <AttentionGroupRow
                    key={item.id}
                    group={item.group}
                    severity={item.severity}
                    editable={editable}
                  />
                );
              }
              const { subject, detail } = attentionTexts(t, item);
              return (
                <li key={item.id} data-severity={item.severity}>
                  <StatusTag kind="integration" status={item.severity}>
                    {t(`attention.severity.${item.severity}`)}
                  </StatusTag>
                  <div className="pf-int-attention-text">
                    <span className="pf-int-attention-subject">{subject}</span>
                    {detail ? <span className="pf-int-attention-detail">{detail}</span> : null}
                    {item.technical ? (
                      <TechnicalDetails
                        lines={[item.technical]}
                        context={{
                          services: subject,
                          state: t(`attention.severity.${item.severity}`),
                          since: "",
                        }}
                      />
                    ) : null}
                  </div>
                  <Link
                    className="pf-focusable"
                    to={cardHref(item.card)}
                    aria-label={t("attention.openAria", { subject })}
                  >
                    {t("open")}
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </section>
  );
}

function CardPanel({ card, editable }: { card: IntegrationCardKey; editable: boolean }) {
  switch (card) {
    case "erp":
      return <ErpPanel editable={editable} />;
    // Telegram, Почта и расходы на ИИ настраиваются на своих страницах — по одному месту (ЕВ-2а, отчёт §8.2 п. 18); «Открыть»
    // ведёт туда (`OWN_PAGE`), а старая ссылка `?card=` уходит по `redirects.ts`: боковых окон этих карточек больше нет.
    case "telegram":
    case "mail":
    case "spend":
      return null;
    case "services":
      return <ServicesPanel editable={editable} />;
    case "models":
      return <ModelsPanel editable={editable} />;
    case "storage":
      return <StoragePanel editable={editable} />;
    case "system":
      return <SystemPanel />;
  }
}

/**
 * Admin · Внешние интеграции (SPEC-v3 §7.6, W13-A1): «Требует внимания» вверху, ниже карточки сервисов — ERP, Telegram, Почта,
 * Внешние сервисы, Модели ИИ, Расходы, Хранилище и бэкапы, Состояние системы. У каждой: статус пятью уровнями словом,
 * последняя проверка, «Проверить»; настройки и формы — в боковом окне (`?card=<карточка>`). Меняет администратор
 * (`admin` — полный); директор (`admin` — чтение) видит то же без кнопок изменения.
 */
export function IntegrationsPage() {
  const { t } = useTranslation(["integrations", "modules"]);
  const { me } = useAuth();
  const [params] = useSearchParams();
  const editable = canEdit(me, "admin");
  const title = t("modules:admin.sections.integrations");
  useDocumentTitle(title);
  const overview = useGetIntegrationsOverview();
  const check = useCardCheck();

  const selectedParam = params.get("card");
  const selected = isCardKey(selectedParam) ? selectedParam : null;

  let body;
  if (overview.isPending) {
    body = <Skeleton active paragraph={{ rows: 8 }} title={false} />;
  } else if (overview.isError) {
    body = (
      <Card>
        <EmptyState
          title={t("integrations:loadError.title")}
          text={t("integrations:loadError.text")}
          action={
            <Button
              onClick={() => {
                void overview.refetch();
              }}
            >
              {t("integrations:common.retry")}
            </Button>
          }
        />
      </Card>
    );
  } else {
    const data = overview.data;
    body = (
      <>
        {/* Карточки настроек — первыми, «Требует внимания» — под ними (S3): первый экран — то, что настраивают */}
        <section aria-labelledby="pf-int-cards">
          <h2 className="pf-int-section-title" id="pf-int-cards" style={{ marginBottom: 12 }}>
            {t("integrations:cardsTitle")}
          </h2>
          <div className="pf-int-grid">
            {data.cards.map((card) => (
              <IntegrationTile
                key={card.key}
                card={card}
                selected={selected === card.key}
                editable={editable}
                running={check.running === card.key}
                outcome={check.outcomes[card.key]}
                onCheck={() => {
                  void check.start(card.key);
                }}
              />
            ))}
          </div>
        </section>
        <AttentionSection items={data.attention} cards={data.cards} editable={editable} />
        {editable ? (
          <Card>
            <CabinetAddress />
          </Card>
        ) : null}
      </>
    );
  }

  return (
    <PageFrame layout="registry" className="pf-int">
      <PageHeader
        title={title}
        readOnly={!editable}
        extra={
          editable ? (
            // Мастер первого запуска остаётся доступным и после завершения шагов (W15-H4): «Настройка Платформы»;
            // «Обмен между системами» — свой пункт группы «Система» (SET-IA).
            <LinkButton to={WIZARD_PATH}>{t("integrations:setupLink")}</LinkButton>
          ) : null
        }
      />
      {body}
      {selected ? (
        <PanelPortal tab="card">
          <CardPanel card={selected} editable={editable} />
        </PanelPortal>
      ) : null}
    </PageFrame>
  );
}
