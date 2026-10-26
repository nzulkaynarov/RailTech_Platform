import type { TFunction } from "i18next";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useGetBotSettings } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { QueryState } from "../../../shared/ui/FormParts";
import { LockIcon } from "../../../shared/ui/icons";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { BotNav } from "./BotNav";
import { ExportsView } from "./ExportsView";
import { useBotStateLabels } from "./labels";
import { SettingsForm } from "./SettingsForm";
import { type JsonSchema } from "./schemaForm";
import { isExtra, resolveSection, sectionGroups } from "./sections";
import { TemplatesView } from "./TemplatesView";

import "./bot.css";

/** Примеры для предпросмотра текстов: название компании — из настроек. */
function samplesOf(t: TFunction, company: unknown): Record<string, string> {
  const samples = t("bot:texts.samples", { returnObjects: true }) as unknown as Record<
    string,
    string
  >;
  return typeof company === "string" && company !== "" ? { ...samples, company } : samples;
}

/**
 * Admin · Настройки бота: разделы настроек CRM (формы по схемам CRM), шаблоны быстрых ответов и выгрузки CSV. Раздел —
 * `?section=`, правка текста или шаблона — в боковом окне. Меняет администратор (`admin` — полный); директор (`admin` —
 * чтение) видит всё без кнопок изменения и без выгрузок.
 */
export function BotPage() {
  const { t } = useTranslation(["bot", "modules"]);
  const { me } = useAuth();
  const editable = canEdit(me, "admin");
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const title = t("modules:admin.sections.bot");
  useDocumentTitle(title);
  const query = useGetBotSettings();
  const labels = useBotStateLabels();
  // Версия формы раздела растёт после сохранения: форма пересоздаётся с перечитанными значениями.
  const [versions, setVersions] = useState<Record<string, number>>({});

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
      <QueryState query={query} labels={labels}>
        {(data) => {
          const keys = Object.keys(data.schemas);
          const section = resolveSection(params.get("section"), keys);
          const hrefOf = (next: string) => `?${new URLSearchParams({ section: next }).toString()}`;
          return (
            <div className="pf-bot-layout">
              <BotNav
                groups={sectionGroups(keys)}
                current={section ?? ""}
                hrefOf={hrefOf}
                onSelect={(next) => {
                  void navigate({ search: hrefOf(next) });
                }}
              />
              <div className="pf-bot-content">
                {section === "templates" ? <TemplatesView editable={editable} /> : null}
                {section === "exports" ? <ExportsView /> : null}
                {section !== null && !isExtra(section) ? (
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
                ) : null}
              </div>
            </div>
          );
        }}
      </QueryState>
    </div>
  );
}
