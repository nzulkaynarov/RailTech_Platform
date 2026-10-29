import { Card } from "antd";
import type { TFunction } from "i18next";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { BotSettings } from "../../../shared/api/generated/model";
import { useGetBotSettings } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { LockIcon } from "../../../shared/ui/icons";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { SectionTabs } from "../company/SectionTabs";
import { TelegramPanel } from "../integrations/TelegramPanel";
import { BotNav } from "./BotNav";
import { ExportsView } from "./ExportsView";
import { useBotStateLabels } from "./labels";
import { SettingsForm } from "./SettingsForm";
import { type JsonSchema } from "./schemaForm";
import {
  BOT_PARTS,
  type BotPart,
  behaviorKeys,
  resolvePart,
  resolveSection,
  sectionGroups,
} from "./sections";
import { TemplatesView } from "./TemplatesView";

import "../company/company.css";
import "../integrations/integrations.css";
import "./bot.css";

/** Где сама база знаний (документы, пробелы, песочница) — существующий экран CRM · База знаний бота. */
const KB_PATH = "/crm/kb";

/** Примеры для предпросмотра текстов: название компании — из настроек. */
function samplesOf(t: TFunction, company: unknown): Record<string, string> {
  const samples = t("bot:texts.samples", { returnObjects: true }) as unknown as Record<
    string,
    string
  >;
  return typeof company === "string" && company !== "" ? { ...samples, company } : samples;
}

/**
 * Настройки · Telegram-бот (W13-A5; W15-H4 — бот в одном месте, UX-оценка §5 P1-6): вкладки «Подключение» (токен, канал
 * команды, профиль — раньше в «Подключениях»), «Тексты», «Поведение и передача» (остальные разделы настроек CRM), «База
 * знаний» (как бот пользуется базой и вход в документы базы), «Шаблоны ответов», «Выгрузки». Вкладка — `?part=`, раздел
 * «Поведения» — `?section=`; правка текста или шаблона — в боковом окне. Меняет администратор (`admin` — полный); директор
 * (`admin` — чтение) видит всё без кнопок изменения и без выгрузок.
 */
export function BotPage() {
  const { t } = useTranslation(["bot", "modules"]);
  const { me } = useAuth();
  const editable = canEdit(me, "admin");
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const title = t("modules:admin.sections.bot");
  useDocumentTitle(title);
  const part = resolvePart(params.get("viewTab") ?? params.get("part"), params.get("section"));
  // Настройки CRM нужны всем вкладкам, кроме «Подключения», шаблонов и выгрузок — там своё API.
  const needsSettings = part === "texts" || part === "behavior" || part === "kb";
  const query = useGetBotSettings({ query: { enabled: needsSettings } });
  const labels = useBotStateLabels();
  // Версия формы раздела растёт после сохранения: форма пересоздаётся с перечитанными значениями.
  const [versions, setVersions] = useState<Record<string, number>>({});

  const form = (data: BotSettings, section: string) => (
    <SettingsForm
      key={`${section}:${String(versions[section] ?? 0)}`}
      settingKey={section}
      title={t(`bot:keys.${section}`, { defaultValue: section })}
      schema={data.schemas[section] as JsonSchema}
      values={data.values[section] ?? {}}
      samples={samplesOf(t, data.values["company"]?.["name"])}
      editable={editable}
      onSaved={() => {
        setVersions((prev) => ({ ...prev, [section]: (prev[section] ?? 0) + 1 }));
      }}
    />
  );

  let body;
  if (part === "connection") {
    body = (
      <Card>
        <TelegramPanel editable={editable} initialTokenOpen />
      </Card>
    );
  } else if (part === "templates") {
    body = <TemplatesView editable={editable} />;
  } else if (part === "exports") {
    body = <ExportsView />;
  } else {
    body = (
      <QueryState query={query} labels={labels}>
        {(data) => {
          const keys = Object.keys(data.schemas);
          if (part === "texts") {
            return keys.includes("texts") ? form(data, "texts") : <p>{t("bot:parts.none")}</p>;
          }
          if (part === "kb") {
            return (
              <div className="pf-panel-stack">
                <Card>
                  <h2 className="pf-bot-part-title">{t("bot:kbEntry.title")}</h2>
                  <p className="pf-hint" style={{ marginTop: 0 }}>
                    {t(editable ? "bot:kbEntry.text" : "bot:kbEntry.readOnlyText")}
                  </p>
                  <LinkButton type="primary" to={KB_PATH}>
                    {t("bot:kbEntry.open")}
                  </LinkButton>
                </Card>
                {keys.includes("kb") ? form(data, "kb") : null}
              </div>
            );
          }
          const behavior = behaviorKeys(keys);
          const section = resolveSection(params.get("section"), behavior);
          const hrefOf = (next: string) =>
            `?${new URLSearchParams({ part: "behavior", section: next }).toString()}`;
          return (
            <div className="pf-bot-layout">
              <BotNav
                groups={sectionGroups(behavior)}
                current={section ?? ""}
                hrefOf={hrefOf}
                onSelect={(next) => {
                  void navigate({ search: hrefOf(next) });
                }}
              />
              <div className="pf-bot-content">
                {section !== null && behavior.includes(section) ? form(data, section) : null}
              </div>
            </div>
          );
        }}
      </QueryState>
    );
  }

  return (
    <div className="pf-bot">
      <PageHeader
        title={title}
        subtitle={t(editable ? "bot:subtitle" : "bot:readOnlySubtitle")}
        extra={
          editable ? null : (
            <StatusTag tone="default">
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <LockIcon size={12} />
                {t("bot:viewOnly")}
              </span>
            </StatusTag>
          )
        }
      />
      <SectionTabs
        label={t("bot:parts.label")}
        active={part}
        tabs={BOT_PARTS.map((key: BotPart) => ({ key, label: t(`bot:parts.${key}`) }))}
        onChange={(key) => {
          setParams(
            (prev) => {
              const next = new URLSearchParams();
              next.set("viewTab", key);
              next.set("part", key);
              const panel = prev.get("panel");
              if (panel) next.set("panel", panel);
              return next;
            },
            { replace: true },
          );
        }}
      >
        {body}
      </SectionTabs>
    </div>
  );
}
