import { Typography } from "antd";
import { useSearchParams } from "react-router";

import { useSettings } from "../../api/adminQueries";
import type { SettingsResponse } from "../../api/generated/model";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import type { JsonSchema } from "../../domain/schemaForm";
import { resolveSection } from "../../domain/settingsLayout";
import { t } from "../../i18n/ru";
import { SettingsForm } from "./SettingsForm";
import { SettingsNav } from "./SettingsNav";
import "../admin.css";

/** Примеры для предпросмотра текстов: название компании — из настроек. */
function previewSamples(data: SettingsResponse): Record<string, string> {
  const name = data.values["company"]?.["name"];
  return {
    ...t.settings.samples,
    company: typeof name === "string" ? name : "",
    hours: t.settings.hoursSample,
  };
}

/**
 * Настройки (admin, PLAN Фаза 5): разделы слева с группами, раздел — в `?section=`
 * (ссылку можно отправить коллеге), формы по Pydantic-схемам, сухой прогон правил передачи.
 */
export function SettingsPage() {
  const query = useSettings();
  const [search, setSearch] = useSearchParams();
  const data = query.data;
  const sections = data ? Object.keys(data.schemas) : [];
  const section = resolveSection(search.get("section"), sections);
  return (
    <PageBody>
      <PageHeader title={t.page.settings} />
      <PageState query={query} ready={Boolean(data && section)}>
        {data && section ? (
          <div className="settings-layout">
            <SettingsNav
              sections={sections}
              current={section}
              onSelect={(next) => {
                setSearch({ section: next });
              }}
            />
            <section aria-labelledby="settings-section-title" className="settings-content">
              <Typography.Title level={2} id="settings-section-title" className="section-title">
                {t.settings.keys[section] ?? section}
              </Typography.Title>
              {t.settings.sectionHints[section] ? (
                <Typography.Paragraph type="secondary">
                  {t.settings.sectionHints[section]}
                </Typography.Paragraph>
              ) : null}
              <SettingsForm
                key={section}
                settingKey={section}
                schema={data.schemas[section] as JsonSchema}
                values={data.values[section] ?? {}}
                samples={previewSamples(data)}
              />
            </section>
          </div>
        ) : null}
      </PageState>
    </PageBody>
  );
}
