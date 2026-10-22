import { App as AntApp, Badge, Divider, Flex } from "antd";

import type { ErpStatusOut, SmtpStatusOut, TelegramStatusOut } from "../../api/generated/model";
import {
  useErpMutations,
  useErpStatus,
  useSmtpMutations,
  useSmtpStatus,
  useTelegramChannels,
  useTelegramMutations,
  useTelegramStatus,
} from "../../api/integrationQueries";
import { useBotProfile } from "../../api/templateQueries";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { UrlTabs } from "../../components/UrlTabs";
import {
  erpTabStatus,
  integrationTabStatus,
  smtpTabStatus,
  type TabStatus,
} from "../../domain/integrations";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { BotProfileCard } from "./BotProfileCard";
import { ErpCard } from "./ErpCard";
import { MailLog } from "./MailLog";
import { SmtpCard } from "./SmtpCard";
import { TeamChannelCard } from "./TeamChannelCard";
import { TelegramBotCard } from "./TelegramBotCard";

const TABS = ["bot", "profile", "channel", "erp", "smtp"] as const;

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

type TabsProps = { status: TelegramStatusOut; erp: ErpStatusOut; smtp: SmtpStatusOut };

function IntegrationTabs({ status, erp, smtp }: TabsProps) {
  const channels = useTelegramChannels();
  const profile = useBotProfile();
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const mutations = useTelegramMutations(onError);
  const erpMutations = useErpMutations(onError);
  const smtpMutations = useSmtpMutations(onError);
  const state = {
    ...integrationTabStatus(status, profile.data),
    erp: erpTabStatus(erp),
    smtp: smtpTabStatus(smtp),
  };
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
    erp: (
      <ErpCard
        status={erp}
        saving={erpMutations.save.isPending}
        checking={erpMutations.check.isPending}
        checkResult={
          erpMutations.check.data ??
          erpMutations.pair.data?.check ??
          erpMutations.rotate.data?.check ??
          null
        }
        checkError={erpMutations.check.error}
        pairing={erpMutations.pair.isPending}
        rotating={erpMutations.rotate.isPending}
        pairError={erpMutations.pair.error}
        pairCheckError={
          erpMutations.check.data
            ? null
            : (erpMutations.pair.data?.check_error ?? erpMutations.rotate.data?.check_error ?? null)
        }
        onPair={(body, done) => {
          erpMutations.rotate.reset();
          erpMutations.check.reset();
          erpMutations.pair.mutate(body, {
            onSuccess: () => {
              done();
              void message.success(t.integrations.erp.pairing.connected);
            },
          });
        }}
        onRotate={(body, done) => {
          erpMutations.pair.reset();
          erpMutations.check.reset();
          erpMutations.rotate.mutate(body, {
            onSuccess: () => {
              done();
              void message.success(t.integrations.erp.pairing.rotated);
            },
          });
        }}
        onSave={(body, done) => {
          erpMutations.save.mutate(body, {
            onSuccess: () => {
              done();
              erpMutations.check.reset();
              void message.success(t.integrations.erp.saved);
            },
          });
        }}
        onCheck={() => {
          erpMutations.pair.reset();
          erpMutations.rotate.reset();
          erpMutations.check.mutate();
        }}
      />
    ),
    smtp: (
      <Flex vertical gap="middle">
        <SmtpCard
          status={smtp}
          saving={smtpMutations.save.isPending}
          checking={smtpMutations.check.isPending}
          testing={smtpMutations.testSend.isPending}
          checkResult={smtpMutations.check.data ?? null}
          checkError={smtpMutations.check.error}
          onSave={(body, done) => {
            smtpMutations.save.mutate(body, {
              onSuccess: () => {
                done();
                smtpMutations.check.reset();
                void message.success(t.integrations.smtp.saved);
              },
            });
          }}
          onCheck={() => {
            smtpMutations.check.mutate();
          }}
          onTestSend={() => {
            smtpMutations.testSend.mutate(undefined, {
              onSuccess: () => void message.success(t.integrations.smtp.testQueued),
            });
          }}
        />
        <Divider />
        <MailLog />
      </Flex>
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
 * «Подключения» (admin): токен бота, профиль бота, канал команды, коннекторы ERP (M3-CRM-02) и
 * «Почта» (M3-CRM-08) без правки `.env` (аудит 2026-10-12); UX волна 3 — вкладками, вкладка в
 * `?tab=`, состояние — значком во вкладке.
 */
export function IntegrationsPage() {
  const status = useTelegramStatus();
  const erp = useErpStatus();
  const smtp = useSmtpStatus();
  const query = {
    isLoading: status.isLoading || erp.isLoading || smtp.isLoading,
    isError: status.isError || erp.isError || smtp.isError,
    error: status.error ?? erp.error ?? smtp.error,
    refetch: () => Promise.all([status.refetch(), erp.refetch(), smtp.refetch()]),
  };
  return (
    <PageBody>
      <PageHeader title={t.page.integrations} />
      <PageState query={query}>
        {status.data && erp.data && smtp.data ? (
          <IntegrationTabs status={status.data} erp={erp.data} smtp={smtp.data} />
        ) : null}
      </PageState>
    </PageBody>
  );
}
