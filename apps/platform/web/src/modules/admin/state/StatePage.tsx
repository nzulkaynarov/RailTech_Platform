import { Card } from "antd";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useSearchParams } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { WIZARD_PATH, visibleTitleKey } from "../../../entities/setup/steps";
import { useSetupProgress } from "../../../features/first-run/useSetupProgress";
import type {
  IntegrationCard,
  IntegrationCardKey,
  IntegrationStatus,
} from "../../../shared/api/generated/model";
import {
  useGetBrandProfile,
  useGetBusJournal,
  useGetFxRate,
  useGetIntegrationsOverview,
  useGetMenuCounters,
  useGetPlatformSettings,
  useGetResponsibilityZonesSummary,
  useListSigningAuthorities,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { attentionTexts } from "../integrations/attentionTexts";
import { SETTINGS, SETTINGS_GROUPS } from "../settingsRegistry";
import {
  type AttentionRow,
  type ReadinessState,
  blankRows,
  busLine,
  fxRows,
  ordered,
  readinessState,
  serviceRows,
  signingRows,
  ticketRows,
  zoneRows,
} from "./model";

import "../settings/settings.css";

/** Какая карточка «Сервисов» проверяет шаг первого запуска: без проверки шаг остаётся «заполнено». */
const STEP_CARD: Partial<Record<string, IntegrationCardKey>> = {
  erp: "erp",
  bot: "telegram",
  mail: "mail",
  models: "models",
};

/** Службы, которые показывает «Состояние»: подпись и карточка обзора с её проверкой. */
const SERVICES: readonly { key: string; card: IntegrationCardKey }[] = [
  { key: "mail", card: "mail" },
  { key: "bot", card: "telegram" },
  { key: "erp", card: "erp" },
  { key: "backups", card: "storage" },
  { key: "ai", card: "spend" },
];

const TONE: Record<IntegrationStatus, "fail" | "warn" | "ok" | "unknown" | "off"> = {
  ok: "ok",
  warn: "warn",
  fail: "fail",
  unknown: "unknown",
  off: "off",
};

function AttentionLine({ row }: { row: AttentionRow }) {
  const { t } = useTranslation(["modules", "integrations"]);
  const { t: tInt } = useTranslation("integrations");
  const { date } = useFormat();
  let title: string;
  let consequence: string;
  let detail: string | null;
  if (row.kind === "service" && row.item) {
    // Тема строки — название карточки: заголовок группы («Ключ OpenAI отклонён») называет поставщика,
    // а «Состояние» читает и директор. У строки-группы `subject` — этот заголовок, поэтому берём карточку.
    const texts = attentionTexts(
      tInt,
      row.item.kind === "service" ? { ...row.item, subject: null } : row.item,
    );
    title =
      row.item.card === "erp" && texts.subject === tInt("cards.erp.title")
        ? t("modules:admin.state.service.erp")
        : texts.subject;
    detail =
      row.item.card === "erp" && row.item.kind === "not_configured"
        ? t("modules:admin.state.erpDetail")
        : texts.detail;
    consequence =
      row.item.group && row.item.group.affected.length > 0
        ? t("modules:admin.state.affected", { list: row.item.group.affected.join(", ") })
        : "";
  } else {
    // Даты — человеческим видом, не `2026-12-07` (СЦ-7)
    const params = {
      ...row.params,
      ...(row.params["until"] ? { until: date(String(row.params["until"])) } : {}),
    };
    title = t(`modules:admin.state.row.${row.kind}.title`, params);
    detail = t(`modules:admin.state.row.${row.kind}.what`, { ...params, defaultValue: "" });
    consequence = t(`modules:admin.state.row.${row.kind}.ifNot`, params);
  }
  const page = row.page ? t(`modules:admin.sections.${row.page}`) : null;
  return (
    <li data-severity={row.severity} data-kind={row.kind}>
      <div className="pf-set-state-text">
        <span className="pf-set-state-title">{title}</span>
        {detail ? <span className="pf-set-state-detail">{detail}</span> : null}
        <span className="pf-set-state-detail">
          {consequence ? `${consequence} · ` : ""}
          {t("modules:admin.state.fixer", { who: t(`modules:admin.state.owner.${row.owner}`) })}
        </span>
      </div>
      {row.to ? (
        <LinkButton to={row.to}>
          {page ? t("modules:admin.state.open", { page }) : t("modules:admin.state.openPlain")}
        </LinkButton>
      ) : null}
    </li>
  );
}

function ServiceLine({
  label,
  card,
  text,
}: {
  label: string;
  card: IntegrationCard | undefined;
  text: string | null;
}) {
  const { t } = useTranslation(["integrations", "modules"]);
  const status: IntegrationStatus = card?.status ?? "unknown";
  return (
    <li>
      <span className="pf-set-state-title">{label}</span>
      <StatusTag kind="integration" status={TONE[status]}>
        {t(`integrations:status.${status}`)}
      </StatusTag>
      {text ? <span className="pf-set-state-detail">{text}</span> : null}
    </li>
  );
}

/**
 * «Состояние» (ЕВ-2а, отчёт 2026-11-22 §8.3; доска 37): первый экран Настроек, открывается по нажатию на модуль.
 * «Требует внимания» — что сломано, что будет, если не исправить, кто исправляет и кнопка к месту; «Службы» — почта, бот,
 * обмен, копии, бюджет ИИ и внешняя проверка доступности (пока «не подключена»); «Готовность» — шаги первого запуска, она
 * остаётся и после настройки, а «работает» ставится только там, где проверка службы подтверждает. Строки выводятся из
 * фактов ответов сервера (`model.ts`). Директор читает; сотрудник без раздела `admin` уходит на первую свою страницу.
 * `?group=` — ⚙ из подменю других модулей: ведёт на первую страницу группы.
 */
export function StatePage() {
  const { t } = useTranslation(["modules", "integrations"]);
  const { me } = useAuth();
  const [params] = useSearchParams();
  useDocumentTitle(t("modules:admin.sections.overview"));

  const isAdmin = canSee(me, { resource: "admin" });
  const asked = params.get("group");
  const group = SETTINGS_GROUPS.find((g) => g === asked);
  const first = SETTINGS.find(
    (entry) => (!group || entry.group === group) && canSee(me, entry.access),
  );
  if ((group || !isAdmin) && first) return <Navigate to={first.path} replace />;

  return <StateBody />;
}

function StateBody() {
  const { t } = useTranslation(["modules", "integrations"]);
  const { me } = useAuth();
  const admin = canEdit(me, "admin");
  const withCompany = canSee(me, { resource: "company.settings" });
  const withSigning = canSee(me, { resource: "eds.signing.manage" });
  const withSystem = canSee(me, { resource: "admin.system" });

  const overview = useGetIntegrationsOverview();
  const counters = useGetMenuCounters({
    query: { enabled: canSee(me, { resource: "dashboard.queue" }) },
  });
  const setup = useSetupProgress(admin);
  const signing = useListSigningAuthorities(
    { status: "all" },
    { query: { enabled: withSigning, retry: false } },
  );
  const fx = useGetFxRate({ currency: "USD" }, { query: { enabled: withCompany, retry: false } });
  const brand = useGetBrandProfile({ query: { enabled: withCompany, retry: false } });
  const platform = useGetPlatformSettings({ query: { enabled: withCompany, retry: false } });
  const bus = useGetBusJournal({ query: { enabled: canEdit(me, "admin"), retry: false } });

  // Зоны без ответственного — тем, кто назначает людей в зоны: полное право «Настройки компании»
  const zones = useGetResponsibilityZonesSummary({
    query: { enabled: canEdit(me, "company.settings"), retry: false },
  });
  const zonesWithout = canEdit(me, "company.settings") ? (zones.data?.without_responsible ?? 0) : 0;
  const tickets =
    counters.data?.items.find((c) => c.module === "admin" && c.section === "tickets")?.count ?? 0;
  // Кнопку к странице, закрытой зрителю, не показываем: остаётся «исправляет администратор»
  const canOpen = (page: string) => {
    const entry = SETTINGS.find((e) => e.key === page);
    return !entry || canSee(me, entry.access);
  };
  const rows = ordered([
    ...serviceRows(overview.data?.attention ?? [], canOpen),
    ...signingRows(signing.data?.items ?? []),
    ...fxRows(fx.data),
    ...blankRows(brand.data),
    ...zoneRows(zonesWithout),
    ...ticketRows(tickets),
  ]);
  const cards = overview.data?.cards ?? [];
  const cardOf = (key: IntegrationCardKey) => cards.find((c) => c.key === key);
  const busTotals = bus.data ? busLine(bus.data.domains) : null;

  // Готовность не исчезает после настройки: те же шаги, плюс бланк и адрес поддержки (их нет в чек-листе сервера)
  const readiness: { key: string; label: string; state: ReadinessState; to: string }[] = [
    ...setup.steps.map((step) => ({
      key: step.key,
      label: t(`modules:${visibleTitleKey(step.key)}`),
      state: readinessState(
        step.state,
        STEP_CARD[step.key] ? cardOf(STEP_CARD[step.key] as IntegrationCardKey)?.status : undefined,
      ),
      to: step.to,
    })),
    ...(brand.data
      ? [
          {
            key: "blank",
            label: t("modules:admin.state.extra.blank"),
            state: (brand.data.logo_url !== null ? "filled" : "todo") as ReadinessState,
            to: "/admin/company?part=brand",
          },
        ]
      : []),
    ...(platform.data
      ? [
          {
            key: "support",
            label: t("modules:admin.state.extra.support"),
            state: (platform.data.support_email !== "" ? "filled" : "todo") as ReadinessState,
            to: "/admin/company#pf-co-part-support",
          },
        ]
      : []),
  ];
  const done = readiness.filter((r) => r.state === "works" || r.state === "filled").length;

  return (
    <div className="pf-set-home">
      <PageHeader title={t("modules:admin.sections.overview")} />
      <section aria-labelledby="pf-set-state-attention">
        <Card styles={{ body: { padding: 0 } }}>
          <h2 className="pf-set-h2 pf-set-state-head" id="pf-set-state-attention">
            {t("modules:admin.state.attention", { count: rows.length })}
          </h2>
          {rows.length === 0 ? (
            <p className="pf-set-state-empty">{t("modules:admin.state.none")}</p>
          ) : (
            <ul className="pf-set-state-list">
              {rows.map((row) => (
                <AttentionLine key={row.id} row={row} />
              ))}
            </ul>
          )}
        </Card>
      </section>
      <section aria-labelledby="pf-set-state-services">
        <Card styles={{ body: { padding: 0 } }}>
          <h2 className="pf-set-h2 pf-set-state-head" id="pf-set-state-services">
            {t("modules:admin.state.services")}
          </h2>
          <ul className="pf-set-state-list pf-set-state-plain">
            {SERVICES.map(({ key, card }) => {
              const found = cardOf(card);
              return (
                <ServiceLine
                  key={key}
                  label={t(`modules:admin.state.service.${key}`)}
                  card={found}
                  text={
                    found
                      ? t(`integrations:notes.${found.note}`, { count: found.count ?? 0 })
                      : null
                  }
                />
              );
            })}
            {withSystem && busTotals ? (
              <li>
                <span className="pf-set-state-title">{t("modules:admin.state.service.bus")}</span>
                <StatusTag kind="integration" status={busTotals.dead > 0 ? "fail" : "ok"}>
                  {t(`integrations:status.${busTotals.dead > 0 ? "fail" : "ok"}`)}
                </StatusTag>
                <span className="pf-set-state-detail">
                  {busTotals.dead > 0
                    ? t("modules:admin.state.bus.dead", { count: busTotals.dead })
                    : busTotals.queued > 0
                      ? t("modules:admin.state.bus.queued", { count: busTotals.queued })
                      : t("modules:admin.state.bus.empty")}
                </span>
              </li>
            ) : null}
            <li data-service="external">
              <span className="pf-set-state-title">{t("modules:admin.state.external.title")}</span>
              <StatusTag kind="integration" status="off">
                {t("modules:admin.state.external.off")}
              </StatusTag>
              <span className="pf-set-state-detail">{t("modules:admin.state.external.text")}</span>
            </li>
          </ul>
          {withSystem ? (
            <p className="pf-set-state-foot">
              <Link className="pf-focusable pf-set-inline" to="/admin/integrations">
                {t("modules:admin.sections.integrations")}
              </Link>
            </p>
          ) : null}
        </Card>
      </section>
      {readiness.length > 0 ? (
        <section aria-labelledby="pf-set-state-ready">
          <Card styles={{ body: { padding: 0 } }}>
            <div className="pf-set-state-bar">
              <h2 className="pf-set-h2 pf-set-state-head" id="pf-set-state-ready">
                {t("modules:admin.state.readiness", { done, total: readiness.length })}
              </h2>
              {setup.next ? (
                <LinkButton type="primary" to={WIZARD_PATH}>
                  {t("modules:admin.setup.banner.open")}
                </LinkButton>
              ) : null}
            </div>
            <ul
              className="pf-set-state-list pf-set-state-plain"
              aria-label={t("modules:admin.setup.listLabel")}
            >
              {readiness.map((row) => (
                <li key={row.key} data-state={row.state}>
                  <Link className="pf-focusable pf-set-state-title" to={row.to}>
                    {row.label}
                  </Link>
                  <span className="pf-set-state-detail">
                    {t(`modules:admin.state.ready.${row.state}`)}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </section>
      ) : null}
    </div>
  );
}
