import { Card } from "antd";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useSearchParams } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { WIZARD_PATH, visibleTitleKey } from "../../../entities/setup/steps";
import { STEP_CARD, UNKNOWN_FACT, cardFact } from "../../../entities/status/facts";
import { useSetupProgress } from "../../../features/first-run/useSetupProgress";
import type { IntegrationCardKey, StatusFact } from "../../../shared/api/generated/model";
import {
  useGetBrandProfile,
  useGetBusJournal,
  useGetFxRate,
  useGetIntegrationsOverview,
  useGetMenuCounters,
  useGetPlatformSettings,
  useListSigningAuthorities,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusStrip } from "../../../shared/ui/StatusStrip";
import { attentionTexts } from "../integrations/attentionTexts";
import { useCardCheck } from "../integrations/useCardCheck";
import { SETTINGS, SETTINGS_GROUPS } from "../settingsRegistry";
import {
  type AttentionRow,
  blankRows,
  busLine,
  busRows,
  fxRows,
  ordered,
  serviceRows,
  signingRows,
  ticketRows,
  unavailableRows,
} from "./model";

import { PageFrame } from "../../../shared/ui/PageFrame";
import "../settings/settings.css";

/** Службы, которые показывает «Состояние»: подпись и карточка обзора с её проверкой (та же, что в «Сервисах»). */
const SERVICES: readonly { key: string; card: IntegrationCardKey }[] = [
  { key: "mail", card: "mail" },
  { key: "bot", card: "telegram" },
  { key: "erp", card: "erp" },
  { key: "backups", card: "storage" },
  { key: "ai", card: "models" },
];

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
  // «Исправляет администратор / директор / бухгалтер» — должности, их на экране нет; называем только внешнюю сторону
  const external = row.owner === "owner" || row.owner === "hosting" || row.owner === "provider";
  return (
    <li data-severity={row.severity} data-kind={row.kind}>
      <div className="pf-set-state-text">
        <span className="pf-set-state-title">{title}</span>
        {detail ? <span className="pf-set-state-detail">{detail}</span> : null}
        <span className="pf-set-state-detail">
          {consequence}
          {consequence && (external || !row.to) ? " · " : ""}
          {external
            ? t("modules:admin.state.fixer", { who: t(`modules:admin.state.owner.${row.owner}`) })
            : row.to
              ? null
              : t("modules:admin.state.handOver")}
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
  fact,
  scope,
  text,
  onCheck,
  checking,
  service,
}: {
  label: string;
  fact: StatusFact;
  scope: string;
  text: string | null;
  onCheck?: () => void;
  checking?: boolean;
  service: string;
}) {
  const { t: tInt } = useTranslation("integrations");
  return (
    <li data-service={service}>
      <span className="pf-set-state-title">{label}</span>
      <StatusStrip
        fact={fact}
        scope={scope}
        {...(onCheck ? { onCheck, checking, checkAria: tInt("checkAria", { title: label }) } : {})}
      />
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
  const check = useCardCheck();

  const tickets =
    counters.data?.items.find((c) => c.module === "admin" && c.section === "tickets")?.count ?? 0;
  // Кнопку к странице, закрытой зрителю, не показываем: остаётся «исправляет администратор»
  const canOpen = (page: string) => {
    const entry = SETTINGS.find((e) => e.key === page);
    return !entry || canSee(me, entry.access);
  };
  // Не ответило — не «проблем нет»: список источников, которые не удалось прочитать, идёт строкой в «Требует внимания»
  const unanswered = [
    overview.isError ? t("modules:admin.state.lists.overview") : null,
    signing.isError ? t("modules:admin.state.lists.signing") : null,
    fx.isError ? t("modules:admin.state.lists.fx") : null,
    brand.isError ? t("modules:admin.state.lists.brand") : null,
    bus.isError ? t("modules:admin.state.lists.bus") : null,
    setup.checklist.isError ? t("modules:admin.state.lists.setup") : null,
  ].filter((name): name is string => name !== null);
  const rows = ordered([
    ...unavailableRows(unanswered),
    ...serviceRows(overview.data?.attention ?? [], canOpen),
    ...busRows(bus.data?.fact, busLine(bus.data?.domains ?? []).dead),
    ...signingRows(signing.data?.items ?? []),
    ...fxRows(fx.data),
    ...blankRows(brand.data),
    ...ticketRows(tickets),
  ]);
  const cardOf = (key: IntegrationCardKey) => cardFact(overview.data, key);
  const busTotals = bus.data ? busLine(bus.data.domains) : null;
  const busFact = bus.data?.fact ?? UNKNOWN_FACT;
  // «Проблем не найдено» — только при полном ответе и службах, которые действительно проверены
  const everyChecked =
    !overview.isPending &&
    SERVICES.every(({ card }) => {
      const state = cardOf(card).state;
      return state === "works" || state === "off";
    });

  const done = setup.done;
  // Бланк и адрес поддержки — не шаги мастера: в счёт «N из M» не входят (счёт один с «Первым запуском»)
  const extras = [
    ...(brand.data
      ? [
          {
            key: "blank",
            label: t("modules:admin.state.extra.blank"),
            ready: brand.data.logo_url !== null,
            to: "/admin/company?part=brand",
          },
        ]
      : []),
    ...(platform.data
      ? [
          {
            key: "support",
            label: t("modules:admin.state.extra.support"),
            ready: platform.data.support_email !== "",
            to: "/admin/company#pf-co-part-support",
          },
        ]
      : []),
  ];

  return (
    <PageFrame layout="registry" className="pf-set-home">
      <PageHeader title={t("modules:admin.sections.overview")} />
      <section aria-labelledby="pf-set-state-attention">
        <Card styles={{ body: { padding: 0 } }}>
          <h2 className="pf-set-h2 pf-set-state-head" id="pf-set-state-attention">
            {t("modules:admin.state.attention", { count: rows.length })}
          </h2>
          {rows.length === 0 ? (
            <p className="pf-set-state-empty">
              {t(everyChecked ? "modules:admin.state.none" : "modules:admin.state.noneUnverified")}
            </p>
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
              const found = overview.data?.cards.find((c) => c.key === card);
              return (
                <ServiceLine
                  key={key}
                  service={key}
                  label={t(`modules:admin.state.service.${key}`)}
                  fact={cardOf(card)}
                  scope={t(`integrations:cards.${card}.scope`)}
                  text={
                    found && found.fact.state !== "works"
                      ? t(`integrations:notes.${found.note}`, { count: found.count ?? 0 })
                      : null
                  }
                  {...(admin
                    ? {
                        onCheck: () => {
                          void check.start(card);
                        },
                        checking: check.running === card,
                      }
                    : {})}
                />
              );
            })}
            {withSystem && (busTotals || bus.isError) ? (
              <ServiceLine
                service="bus"
                label={t("modules:admin.state.service.bus")}
                fact={busFact}
                scope={t("modules:admin.state.busScope")}
                text={
                  busFact.state === "unknown"
                    ? null
                    : busTotals && busTotals.dead > 0
                      ? t("modules:admin.state.bus.dead", { count: busTotals.dead })
                      : busTotals && busTotals.queued > 0
                        ? t("modules:admin.state.bus.queued", { count: busTotals.queued })
                        : t("modules:admin.state.bus.empty")
                }
              />
            ) : null}
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
      {setup.steps.length > 0 || extras.length > 0 ? (
        <section aria-labelledby="pf-set-state-ready">
          <Card styles={{ body: { padding: 0 } }}>
            <div className="pf-set-state-bar">
              <h2 className="pf-set-h2 pf-set-state-head" id="pf-set-state-ready">
                {setup.steps.length > 0
                  ? t("modules:admin.state.readiness", { done, total: setup.steps.length })
                  : t("modules:admin.state.readinessPlain")}
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
              {setup.steps.map((step) => (
                <li key={step.key} data-state={step.verdict}>
                  <Link className="pf-focusable pf-set-state-title" to={step.to}>
                    {t(`modules:${visibleTitleKey(step.key)}`)}
                  </Link>
                  {step.fact && step.state === "done" ? (
                    <StatusStrip
                      fact={step.fact}
                      scope={t(
                        `integrations:cards.${(STEP_CARD as Record<string, IntegrationCardKey>)[step.key] ?? "erp"}.scope`,
                      )}
                    />
                  ) : (
                    <span className="pf-set-state-detail">
                      {t(`modules:admin.state.ready.${step.verdict}`)}
                    </span>
                  )}
                </li>
              ))}
              {extras.map((row) => (
                <li key={row.key} data-state={row.ready ? "done" : "todo"}>
                  <Link className="pf-focusable pf-set-state-title" to={row.to}>
                    {row.label}
                  </Link>
                  <span className="pf-set-state-detail">
                    {t(`modules:admin.state.ready.${row.ready ? "done" : "todo"}`)} ·{" "}
                    {t("modules:admin.state.notCounted")}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </section>
      ) : null}
    </PageFrame>
  );
}
