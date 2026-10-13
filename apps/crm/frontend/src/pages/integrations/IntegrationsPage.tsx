import { App as AntApp, Badge } from "antd";

import type { TelegramStatusOut } from "../../api/generated/model";
import {
  useTelegramChannels,
  useTelegramMutations,
  useTelegramStatus,
} from "../../api/integrationQueries";
import { useBotProfile } from "../../api/templateQueries";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { UrlTabs } from "../../components/UrlTabs";
import { integrationTabStatus, type TabStatus } from "../../domain/integrations";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { BotProfileCard } from "./BotProfileCard";
import { TeamChannelCard } from "./TeamChannelCard";
import { TelegramBotCard } from "./TelegramBotCard";

const TABS = ["bot", "profile", "channel"] as const;

/** Название вкладки со значком состояния; состояние продублировано текстом для экранного диктора. */
function TabLabel({ tab, status }: { tab: string; status: TabStatus | null }) {
  const label = t.integrations.tabs[tab];
  if (!status) return <>{label}</>;
  return (
    <span>
      <Badge status={status} text={label} />
      <span className="sr-only">: {t.integrations.tabState[status]}</span>
    </span>
  );
}

function IntegrationTabs({ status }: { status: TelegramStatusOut }) {
  const channels = useTelegramChannels();
  const profile = useBotProfile();
  const { message } = AntApp.useApp();
  const mutations = useTelegramMutations(useApiErrorToast());
  const state = integrationTabStatus(status, profile.data);
  const content = {
    bot: (
      <TelegramBotCard
        status={status}
        saving={mutations.saveToken.isPending}
        onSave={(body, done) => {
          mutations.saveToken.mutate(body, {
            onSuccess: (next) => {
              done();
              void message.success(t.integrations.saved.replace("{username}", next.username ?? ""));
            },
          });
        }}
      />
    ),
    profile: <BotProfileCard />,
    channel: (
      <TeamChannelCard
        status={status}
        channels={channels}
        connecting={mutations.connect.isPending}
        testing={mutations.sendTest.isPending}
        onConnect={(chatId) => {
          mutations.connect.mutate(chatId, {
            onSuccess: () => void message.success(t.integrations.connected),
          });
        }}
        onTest={() => {
          mutations.sendTest.mutate(undefined, {
            onSuccess: () => void message.success(t.integrations.testSent),
          });
        }}
      />
    ),
  };
  return (
    <UrlTabs
      label={t.integrations.sections}
      items={TABS.map((tab) => ({
        key: tab,
        label: <TabLabel tab={tab} status={state[tab]} />,
        children: content[tab],
      }))}
    />
  );
}

/**
 * «Подключения» (admin): токен бота, профиль бота и канал команды без правки `.env`
 * (аудит 2026-10-12); UX волна 3 — вкладками, вкладка в `?tab=`, состояние — значком во вкладке.
 */
export function IntegrationsPage() {
  const status = useTelegramStatus();
  return (
    <PageBody>
      <PageHeader title={t.page.integrations} />
      <PageState query={status}>
        {status.data ? <IntegrationTabs status={status.data} /> : null}
      </PageState>
    </PageBody>
  );
}
