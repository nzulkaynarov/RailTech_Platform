import { Input } from "antd";
import { useEffect, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import {
  STEP_TARGET,
  WIZARD_PATH,
  bankDetailsMissing,
  needsSetup,
} from "../../../entities/setup/steps";
import { useSetupChecklist } from "../../../features/first-run/useSetupChecklist";
import type {
  IntegrationCardKey,
  IntegrationStatus,
  IntegrationsOverview,
  SetupChecklist,
} from "../../../shared/api/generated/model";
import {
  useGetIntegrationsOverview,
  useGetMenuCounters,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { SearchIcon } from "../../../shared/ui/icons";
import { LevelTag } from "../integrations/parts";
import {
  GROUP_NAMES,
  SETTINGS,
  SETTINGS_GROUPS,
  type SettingEntry,
  type SettingHit,
  type SettingsGroup,
  langOf,
  searchSettings,
} from "../settingsRegistry";

import "./settings.css";

const WORST: readonly IntegrationStatus[] = ["fail", "warn", "unknown", "ok"];

/** Плашка состояния карточки — только там, где есть данные: каналы, подключения, расходы (обзор «Подключений»). */
function statusOf(
  key: string,
  overview: IntegrationsOverview | undefined,
): IntegrationStatus | null {
  if (!overview) return null;
  const card = (k: IntegrationCardKey) => overview.cards.find((c) => c.key === k);
  const own: Partial<Record<string, IntegrationCardKey>> = {
    telegram: "telegram",
    mail: "mail",
    spend: "spend",
  };
  const mine = own[key];
  if (mine) {
    const status = card(mine)?.status;
    return status && status !== "off" ? status : null;
  }
  if (key === "integrations") {
    const levels = overview.cards
      .filter((c) => !["telegram", "mail", "spend"].includes(c.key))
      .map((c) => c.status);
    return WORST.find((level) => levels.includes(level)) ?? null;
  }
  return null;
}

function SettingCard({
  entry,
  status,
  hint,
  groupLabel,
}: {
  entry: SettingEntry;
  status: IntegrationStatus | null;
  hint?: string | undefined;
  groupLabel?: string | undefined;
}) {
  const { t, i18n } = useTranslation("modules");
  const id = useId();
  return (
    <li>
      <Link to={entry.path} className="pf-set-tile pf-focusable" aria-describedby={`${id}-d`}>
        <span className="pf-set-tile-head">
          <span className="pf-set-tile-title">{t(`admin.sections.${entry.key}`)}</span>
          {status ? <LevelTag level={status} /> : null}
        </span>
        <span className="pf-set-tile-desc" id={`${id}-d`}>
          {groupLabel ? `${groupLabel}. ` : ""}
          {entry.description[langOf(i18n.language)]}
        </span>
        {hint ? (
          <span className="pf-set-tile-hit">{t("admin.home.matchedBy", { word: hint })}</span>
        ) : null}
      </Link>
    </li>
  );
}

/** Чек-лист первого запуска (Shopify setup guide): пока не завершён — над группами; шаги и их число — из данных BFF. */
function FirstRunChecklist({ data }: { data: SetupChecklist }) {
  const { t } = useTranslation("modules");
  const notes = [
    data.company?.required ? t("admin.setup.banner.company") : null,
    bankDetailsMissing(data) ? t("admin.setup.banner.bank") : null,
  ].filter(Boolean);
  return (
    <section className="pf-set-setup" aria-labelledby="pf-set-setup-title">
      <div className="pf-set-setup-head">
        <h2 className="pf-set-h2" id="pf-set-setup-title">
          {t("admin.home.setupTitle", { done: data.done, total: data.total })}
        </h2>
        <LinkButton type="primary" to={WIZARD_PATH}>
          {t("admin.setup.banner.open")}
        </LinkButton>
      </div>
      {notes.length > 0 ? <p className="pf-set-setup-note">{notes.join(" ")}</p> : null}
      <ol className="pf-set-steps" aria-label={t("admin.setup.listLabel")}>
        {data.steps.map((step) => (
          <li key={step.key} data-state={step.state}>
            <span className="pf-set-step-mark" aria-hidden="true" />
            {step.state === "todo" ? (
              <Link className="pf-focusable" to={STEP_TARGET[step.key]}>
                {t(`admin.setup.steps.${step.key}.title`)}
              </Link>
            ) : (
              <span>{t(`admin.setup.steps.${step.key}.title`)}</span>
            )}
            <span className="pf-set-step-state">{t(`admin.setup.state.${step.state}`)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * Индекс Настроек `/admin` (SET-IA; эталоны — Shopify admin settings и setup guide, Stripe, HubSpot): строка поиска по реестру
 * настроек, чек-лист «Первый запуск», пока он не завершён, счётчик обращений сотрудников (они — в «Моих задачах») и пять групп
 * карточек. Карточка — название до 3 слов, строка до 60 знаков и плашка состояния, если есть данные. Показываются только
 * доступные ролям страницы (`canSee`); директору — те же карточки, страницы откроются на чтение. `?group=` — к своей группе
 * (⚙ в подменю модуля).
 */
export function SettingsHome() {
  const { t, i18n } = useTranslation("modules");
  const { me } = useAuth();
  const [params] = useSearchParams();
  const [query, setQuery] = useState("");
  const searchId = useId();
  const title = t("admin.sections.overview");
  useDocumentTitle(title);

  const allowed = (entry: SettingEntry) => canSee(me, entry.access);
  const visible = SETTINGS.filter(allowed);
  const admin = canEdit(me, "admin");
  const checklist = useSetupChecklist(admin);
  const overview = useGetIntegrationsOverview({
    query: { enabled: canSee(me, { resource: "admin" }) },
  });
  const counters = useGetMenuCounters({
    query: { enabled: canSee(me, { resource: "dashboard.queue" }) },
  });
  const tickets =
    counters.data?.items.find((c) => c.module === "admin" && c.section === "tickets")?.count ?? 0;

  const lang = langOf(i18n.language);
  const hits: SettingHit[] = useMemo(
    () => searchSettings(query, lang, (entry) => canSee(me, entry.access)),
    [query, lang, me],
  );
  const searching = query.trim().length >= 2;

  // ⚙ из подменю модуля ведёт на свою группу: прокрутить к ней (HubSpot: из инструмента — сразу в его настройки).
  const focusGroup = params.get("group");
  useEffect(() => {
    if (!focusGroup) return;
    document.getElementById(`pf-set-group-${focusGroup}`)?.scrollIntoView({ block: "start" });
  }, [focusGroup]);

  const status = (key: string) => statusOf(key, overview.data);

  return (
    <div className="pf-set-home">
      <PageHeader title={title} />
      <div className="pf-set-search" role="search">
        <label htmlFor={searchId} className="pf-sr-only">
          {t("admin.home.searchLabel")}
        </label>
        <Input
          id={searchId}
          type="search"
          size="large"
          allowClear
          autoComplete="off"
          prefix={<SearchIcon />}
          placeholder={t("admin.home.searchPlaceholder")}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
      </div>
      <div role="status" className="pf-sr-only">
        {searching ? t("admin.home.found", { count: hits.length }) : ""}
      </div>
      {searching ? (
        hits.length > 0 ? (
          <section aria-label={t("admin.home.results")}>
            <ul className="pf-set-grid">
              {hits.map((hit) => (
                <SettingCard
                  key={hit.entry.key}
                  entry={hit.entry}
                  status={status(hit.entry.key)}
                  hint={hit.matchedBy}
                  groupLabel={GROUP_NAMES[hit.entry.group][lang]}
                />
              ))}
            </ul>
          </section>
        ) : (
          <div className="pf-set-empty">
            <p>{t("admin.home.none", { query: query.trim() })}</p>
            <button
              type="button"
              className="pf-set-link pf-focusable"
              onClick={() => {
                setQuery("");
              }}
            >
              {t("admin.home.clear")}
            </button>
          </div>
        )
      ) : (
        <>
          {admin && checklist.data && needsSetup(checklist.data) ? (
            <FirstRunChecklist data={checklist.data} />
          ) : null}
          {canSee(me, { resource: "admin" }) ? (
            <p className="pf-set-tickets">
              {t("admin.home.tickets", { count: tickets })}{" "}
              <Link className="pf-focusable pf-set-inline" to="/dashboard/queue">
                {t("admin.home.ticketsLink")}
              </Link>
            </p>
          ) : null}
          {SETTINGS_GROUPS.map((group: SettingsGroup) => {
            const entries = visible.filter((entry) => entry.group === group);
            if (entries.length === 0) return null;
            return (
              <section
                key={group}
                id={`pf-set-group-${group}`}
                className="pf-set-group"
                data-focused={focusGroup === group ? "true" : undefined}
                aria-labelledby={`pf-set-group-${group}-title`}
              >
                <h2 className="pf-set-h2" id={`pf-set-group-${group}-title`}>
                  {t(`admin.groups.${group}`)}
                </h2>
                <ul className="pf-set-grid">
                  {entries.map((entry) => (
                    <SettingCard key={entry.key} entry={entry} status={status(entry.key)} />
                  ))}
                </ul>
              </section>
            );
          })}
        </>
      )}
    </div>
  );
}
