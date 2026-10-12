import { App as AntApp, Flex } from "antd";

import {
  useTelegramChannels,
  useTelegramMutations,
  useTelegramStatus,
} from "../../api/integrationQueries";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { BotProfileCard } from "./BotProfileCard";
import { TeamChannelCard } from "./TeamChannelCard";
import { TelegramBotCard } from "./TelegramBotCard";

/** «Подключения» (admin): токен бота и канал команды без правки `.env` (аудит 2026-10-12). */
export function IntegrationsPage() {
  const status = useTelegramStatus();
  const channels = useTelegramChannels();
  const { message } = AntApp.useApp();
  const mutations = useTelegramMutations(useApiErrorToast());
  return (
    <PageBody>
      <PageHeader title={t.page.integrations} />
      <PageState query={status}>
        {status.data ? (
          <Flex vertical gap="middle">
            <TelegramBotCard
              status={status.data}
              saving={mutations.saveToken.isPending}
              onSave={(body, done) => {
                mutations.saveToken.mutate(body, {
                  onSuccess: (next) => {
                    done();
                    void message.success(
                      t.integrations.saved.replace("{username}", next.username ?? ""),
                    );
                  },
                });
              }}
            />
            <BotProfileCard />
            <TeamChannelCard
              status={status.data}
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
          </Flex>
        ) : null}
      </PageState>
    </PageBody>
  );
}
