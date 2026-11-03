import type { TFunction } from "i18next";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { BotSettings } from "../../../shared/api/generated/model";
import { useGetBotSettings } from "../../../shared/api/generated/platform-bff";
import { QueryState } from "../../../shared/ui/FormParts";
import { useBotStateLabels } from "../bot/labels";
import { type JsonSchema } from "../bot/schemaForm";
import { botSectionsFor } from "../bot/sections";
import { SettingsForm } from "../bot/SettingsForm";

import "../bot/bot.css";

/** Примеры для предпросмотра текстов: название компании — из настроек. */
function samplesOf(t: TFunction, company: unknown): Record<string, string> {
  const samples = t("bot:texts.samples", { returnObjects: true }) as unknown as Record<
    string,
    string
  >;
  return typeof company === "string" && company !== "" ? { ...samples, company } : samples;
}

/** Формы разделов настроек бота одной страницы, одна под другой; версия формы растёт после сохранения — форма пересоздаётся. */
function Forms({ data, keys }: { data: BotSettings; keys: readonly string[] }) {
  const { t } = useTranslation(["bot"]);
  const { me } = useAuth();
  const editable = canEdit(me, "admin");
  const [versions, setVersions] = useState<Record<string, number>>({});
  return (
    <>
      {keys.map((section) => (
        <section
          key={section}
          className="pf-set-card"
          aria-labelledby={`pf-bot-section-${section}`}
        >
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
        </section>
      ))}
    </>
  );
}

/**
 * Разделы настроек бота, которые после SET-IA живут на этой странице Настроек (`page` — ключ из `BOT_PLACEMENT`): «Время и
 * сроки» — рабочие часы и правила передачи, «Уведомления» — канал команды и сбои, и т. д. Данные — один запрос настроек.
 */
export function BotSettingsSections({ page }: { page: string }) {
  const { t } = useTranslation("bot");
  const query = useGetBotSettings();
  const labels = useBotStateLabels();
  return (
    <QueryState query={query} labels={labels}>
      {(data) => {
        const keys = botSectionsFor(page, Object.keys(data.schemas));
        if (keys.length === 0) return <p className="pf-hint">{t("parts.none")}</p>;
        return <Forms data={data} keys={keys} />;
      }}
    </QueryState>
  );
}
