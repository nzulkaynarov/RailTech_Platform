import { Card, Tag } from "antd";
import { useTranslation } from "react-i18next";

/** Названия сервисов-брендов остаются как есть; своё слово — ключ `catalog.names.*`. */
interface Connector {
  name?: string;
  label?: string;
}

const CATALOG: readonly { group: string; items: readonly Connector[] }[] = [
  {
    group: "tasks",
    items: [
      { name: "Яндекс Трекер" },
      { name: "Jira" },
      { name: "Notion" },
      { name: "Google Tasks" },
      { name: "Битрикс24" },
    ],
  },
  {
    group: "chats",
    items: [
      { name: "Яндекс Мессенджер" },
      { name: "Телемост" },
      { name: "Google Chat" },
      { name: "Microsoft Teams" },
    ],
  },
  {
    group: "calendar",
    items: [
      { name: "Яндекс Календарь" },
      { name: "Google Календарь" },
      { label: "caldav" },
      { label: "contacts" },
    ],
  },
  { group: "files", items: [{ name: "Google Диск" }] },
  {
    group: "documents",
    items: [{ name: "Didox" }, { name: "E-IMZO" }, { label: "banks" }, { name: "1С" }],
  },
  { group: "other", items: [{ label: "api" }] },
];

/** Настройки · Подключения: сервисы, которые подключатся следующими. */
export function ConnectorCatalog() {
  const { t } = useTranslation("integrations");
  return (
    <section aria-labelledby="pf-int-catalog" className="pf-int-catalog">
      <h2 className="pf-int-section-title" id="pf-int-catalog">
        {t("catalog.title")}
      </h2>
      {CATALOG.map(({ group, items }) => (
        <section key={group} aria-label={t(`catalog.groups.${group}`)}>
          <h3 className="pf-int-catalog-group">{t(`catalog.groups.${group}`)}</h3>
          <div className="pf-int-catalog-grid">
            {items.map((item) => {
              const name = item.name ?? t(`catalog.names.${item.label ?? ""}`);
              return (
                <Card key={name} size="small">
                  <div className="pf-int-catalog-tile">
                    <span>{name}</span>
                    <Tag>{t("catalog.soon")}</Tag>
                  </div>
                </Card>
              );
            })}
          </div>
        </section>
      ))}
    </section>
  );
}
