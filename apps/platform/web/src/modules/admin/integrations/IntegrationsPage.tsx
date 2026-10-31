import { Alert, Button, Card, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import type {
  AttentionItem,
  IntegrationCard,
  IntegrationCardKey,
  IntegrationStatus,
} from "../../../shared/api/generated/model";
import {
  checkErpConnector,
  checkExternalService,
  checkSmtp,
  listExternalServices,
  useGetIntegrationsOverview,
} from "../../../shared/api/generated/platform-bff";
import { WIZARD_PATH } from "../../../entities/setup/steps";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { LockIcon } from "../../../shared/ui/icons";
import { AttentionGroupRow } from "./AttentionGroup";
import { integrationErrorText } from "./errors";
import { TechnicalDetails } from "./HealthParts";
import { ErpPanel } from "./ErpPanel";
import { MailPanel } from "./MailPanel";
import { ModelsPanel } from "./ModelsPanel";
import { LevelTag } from "./parts";
import { useRefreshIntegrations } from "./refresh";
import { ServicesPanel } from "./ServicesPanel";
import { SpendPanel } from "./SpendPanel";
import { StoragePanel } from "./StoragePanel";
import { SystemPanel } from "./SystemPanel";
import { TelegramPanel } from "./TelegramPanel";

import "./integrations.css";

const PATH = "/admin/integrations";
const BUS_PATH = "/admin/bus";
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

function isCardKey(value: string | null): value is IntegrationCardKey {
  return value !== null && (CARD_KEYS as readonly string[]).includes(value);
}

const WORST_ORDER: readonly IntegrationStatus[] = ["fail", "warn", "unknown", "ok", "off"];

function worstOf(levels: readonly IntegrationStatus[]): IntegrationStatus {
  return WORST_ORDER.find((level) => levels.includes(level)) ?? "unknown";
}

interface CheckOutcome {
  level: IntegrationStatus | "error";
  text: string;
}

/**
 * «Проверить» на карточке: запускает проверки её сервисов в CRM (реестр внешних сервисов, ADR-0024 CRM) и сразу
 * показывает итог словами. Карточки «Расходы» и «Состояние системы» — отчёты: у них «Обновить».
 */
function useCardCheck() {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const [running, setRunning] = useState<IntegrationCardKey | null>(null);
  const [outcomes, setOutcomes] = useState<Partial<Record<IntegrationCardKey, CheckOutcome>>>({});

  const serviceKeys = async (match: (key: string) => boolean): Promise<string[]> => {
    const list = await listExternalServices();
    return list.items
      .filter((service) => service.status !== "off" && match(service.key))
      .map((service) => service.key);
  };

  const levels = async (keys: readonly string[]): Promise<IntegrationStatus[]> =>
    Promise.all(
      keys.map((key) => checkExternalService(key).then((detail) => detail.service.status)),
    );

  const run = async (key: IntegrationCardKey): Promise<IntegrationStatus> => {
    switch (key) {
      case "erp": {
        const result = await checkErpConnector();
        return result.status === "ok" ? "ok" : "warn";
      }
      case "mail": {
        const result = await checkSmtp();
        return result.authenticated ? "ok" : "warn";
      }
      case "telegram":
        return worstOf(await levels(["telegram"]));
      case "services":
        return worstOf(await levels(await serviceKeys(() => true)));
      case "models":
        return worstOf(
          await levels(await serviceKeys((k) => k === "litellm" || k.startsWith("vendor."))),
        );
      case "storage":
        return worstOf(await levels(await serviceKeys((k) => k === "s3" || k === "backup")));
      default:
        return "ok";
    }
  };

  const start = async (key: IntegrationCardKey) => {
    setRunning(key);
    setOutcomes((prev) => ({ ...prev, [key]: undefined }));
    try {
      if (key === "spend" || key === "system") {
        refresh();
        setOutcomes((prev) => ({ ...prev, [key]: { level: "ok", text: t("check.refreshed") } }));
        return;
      }
      const level = await run(key);
      setOutcomes((prev) => ({
        ...prev,
        [key]: { level, text: t("check.result", { status: t(`status.${level}`) }) },
      }));
      refresh();
    } catch (error) {
      setOutcomes((prev) => ({
        ...prev,
        [key]: { level: "error", text: integrationErrorText(t, error) },
      }));
    } finally {
      setRunning(null);
    }
  };
  return { running, outcomes, start };
}

function noteText(t: ReturnType<typeof useTranslation>["t"], card: IntegrationCard): string {
  if (card.access === "forbidden") return t("access.forbidden");
  if (card.access === "unavailable") return t("access.unavailable");
  // «Всё в порядке» не может стоять рядом с бейджем «Нет данных»: состояние неизвестно — так и пишем (W15-G-6).
  const note = card.note === "all_ok" && card.status === "unknown" ? "no_data" : card.note;
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
  const { date, money } = useFormat();
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
        <LevelTag level={card.status} />
      </div>
      <p className="pf-int-card-purpose">{t(`cards.${card.key}.purpose`)}</p>
      <p className="pf-int-card-note">{noteText(t, card)}</p>
      {card.key === "spend" && card.amount_usd !== null && card.access === "ok" ? (
        <p className="pf-int-card-note">{t("spendToday", { amount: usd(card.amount_usd) })}</p>
      ) : null}
      <p className="pf-hint" style={{ margin: 0 }}>
        {card.last_activity_at
          ? t("lastActivity", { date: date(card.last_activity_at, "datetime") })
          : t("noActivity")}
      </p>
      {outcome ? (
        <Alert
          type={
            outcome.level === "error" ? "error" : outcome.level === "ok" ? "success" : "warning"
          }
          showIcon
          role={outcome.level === "error" ? "alert" : "status"}
          message={outcome.text}
        />
      ) : null}
      <div className="pf-int-card-foot">
        <LinkButton
          to={`${PATH}?card=${card.key}&panel=open`}
          aria-label={t("openAria", { title })}
          aria-current={selected ? "true" : undefined}
        >
          {t("open")}
        </LinkButton>
        {editable || isReport ? (
          <Button
            loading={running}
            aria-label={t(isReport ? "refreshAria" : "checkAria", { title })}
            disabled={card.access === "forbidden"}
            onClick={onCheck}
          >
            {t(isReport ? "common.refresh" : "common.check")}
          </Button>
        ) : null}
      </div>
    </article>
  );
}

function attentionTexts(
  t: ReturnType<typeof useTranslation>["t"],
  item: AttentionItem,
): { subject: string; detail: string | null } {
  const card = t(`cards.${item.card}.title`);
  switch (item.kind) {
    case "not_configured":
      return { subject: card, detail: t(`attention.notConfigured.${item.card}`) };
    case "model_problem": {
      const alias = t(`models.alias.${item.subject ?? ""}`, { defaultValue: item.subject ?? card });
      return { subject: alias, detail: t("health.model.problem", { alias }) };
    }
    case "backup_stale":
      return {
        subject: card,
        detail: [t("attention.backupStale"), item.detail].filter(Boolean).join(" "),
      };
    case "rotation_pending":
      return { subject: card, detail: t("attention.rotationPending") };
    case "bot_not_running":
      return {
        subject: card,
        detail: [t("attention.botNotRunning"), item.detail].filter(Boolean).join(" "),
      };
    case "paused":
      return {
        subject: item.subject ?? card,
        detail: [t("attention.paused"), item.detail].filter(Boolean).join(" "),
      };
    case "budget_over":
    case "budget_near":
      return {
        subject: item.subject ?? card,
        detail: `${t(`attention.${item.kind}`)} ${item.detail ?? ""}`.trim(),
      };
    default:
      return { subject: item.subject ?? card, detail: item.detail };
  }
}

function AttentionSection({
  items,
  editable,
}: {
  items: readonly AttentionItem[];
  editable: boolean;
}) {
  const { t } = useTranslation("integrations");
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
          <p className="pf-int-empty">{t("attention.empty")}</p>
        ) : (
          <ul className="pf-int-attention">
            {items.map((item) => {
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
                    to={`${PATH}?card=${item.card}&panel=open`}
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
    case "telegram":
      // Бот настраивается в одном месте — Настройки · Telegram-бот (W15-H4); здесь — состояние и переход туда.
      return <TelegramPanel editable={editable} summary />;
    case "mail":
      return <MailPanel editable={editable} />;
    case "services":
      return <ServicesPanel editable={editable} />;
    case "models":
      return <ModelsPanel editable={editable} />;
    case "spend":
      return <SpendPanel />;
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
        <AttentionSection items={data.attention} editable={editable} />
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
      </>
    );
  }

  return (
    <div className="pf-int">
      <PageHeader
        title={title}
        subtitle={t(editable ? "integrations:subtitle" : "integrations:readOnlySubtitle")}
        extra={
          editable ? (
            // Мастер первого запуска остаётся доступным и после завершения шагов (W15-H4): «Настройка Платформы»;
            // журнал шины — «Обмен между системами» (только `admin: full`, как и сам журнал).
            <div className="pf-int-row">
              <LinkButton to={BUS_PATH}>{t("modules:admin.journal.systems")}</LinkButton>
              <LinkButton to={WIZARD_PATH}>{t("integrations:setupLink")}</LinkButton>
            </div>
          ) : (
            <StatusTag tone="default">
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <LockIcon size={12} />
                {t("integrations:viewOnly")}
              </span>
            </StatusTag>
          )
        }
      />
      {body}
      {selected ? (
        <PanelPortal tab="card">
          <CardPanel card={selected} editable={editable} />
        </PanelPortal>
      ) : null}
    </div>
  );
}
