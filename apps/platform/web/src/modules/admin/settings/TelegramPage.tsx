import { Card } from "antd";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { TemplatesView } from "../bot/TemplatesView";
import { SectionTabs } from "../company/SectionTabs";
import { TelegramPanel } from "../integrations/TelegramPanel";
import { BotSettingsSections } from "./BotSettingsSections";
import { SettingsPage } from "./SettingsPage";
import { useTabParam } from "./useTabParam";

import "../company/company.css";
import "../integrations/integrations.css";

const TABS = ["connection", "texts", "behavior", "templates", "kb"] as const;

/** Где сама база знаний (документы, пробелы, песочница) — экран Клиенты · База знаний бота. */
const KB_PATH = "/crm/kb";

/**
 * Каналы связи · Telegram (SET-IA; DECISIONS 2026-10-28 «одна страница канала»): бывший «Telegram-бот» без вложенных вкладок.
 * Один уровень вкладок (`?tab=`): «Подключение» (токен, канал команды, профиль), «Тексты», «Поведение» (поведение бота,
 * квалификация, стоп-слова, конкуренты — формами одна под другой), «Шаблоны ответов», «База знаний». Остальные разделы бота —
 * на страницах своих групп (`BOT_PLACEMENT`). Меняет `admin: full`; директор видит без кнопок.
 */
export function TelegramPage() {
  const { t } = useTranslation(["bot", "modules"]);
  const { me } = useAuth();
  const editable = canEdit(me, "admin");
  const [active, select] = useTabParam(TABS);

  let body;
  if (active === "connection") {
    body = (
      <Card>
        <TelegramPanel editable={editable} initialTokenOpen titled={false} />
      </Card>
    );
  } else if (active === "templates") {
    body = <TemplatesView editable={editable} />;
  } else if (active === "kb") {
    body = (
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
        <BotSettingsSections page="telegram.kb" />
      </div>
    );
  } else {
    body = (
      <div className="pf-panel-stack">
        <BotSettingsSections page={`telegram.${active}`} />
      </div>
    );
  }

  return (
    <SettingsPage sectionKey="telegram">
      <SectionTabs
        label={t("bot:parts.label")}
        active={active}
        tabs={TABS.map((key) => ({ key, label: t(`bot:parts.${key}`) }))}
        onChange={select}
      >
        {body}
      </SectionTabs>
    </SettingsPage>
  );
}
