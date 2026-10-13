import { ReloadOutlined, SendOutlined } from "@ant-design/icons";
import type { UseQueryResult } from "@tanstack/react-query";
import { Button, Descriptions, Flex, List, Tag, Typography } from "antd";
import { useState } from "react";

import type { ChatCandidateOut, TelegramStatusOut } from "../../api/generated/model";
import { EmptyState } from "../../components/EmptyState";
import { PageState } from "../../components/PageState";
import { channelLabel } from "../../domain/integrations";
import { t } from "../../i18n/ru";

type Props = {
  status: TelegramStatusOut;
  channels: UseQueryResult<ChatCandidateOut[]>;
  connecting: boolean;
  testing: boolean;
  onConnect: (chatId: number) => void;
  onTest: () => void;
};

/** Вкладка «Канал команды»: найденные по `my_chat_member` каналы, «Подключить», тестовое сообщение. */
export function TeamChannelCard({
  status,
  channels,
  connecting,
  testing,
  onConnect,
  onTest,
}: Props) {
  const current = channelLabel(
    status.channel_id,
    status.channel_title,
    t.integrations.channelUnknownTitle,
  );
  const connected = status.channel_id !== null;
  // Канал уже подключён — список найденных раскрывается по «Найти другой».
  const [browse, setBrowse] = useState(false);
  const showList = !connected || browse;
  return (
    <Flex vertical gap="middle">
      <Typography.Paragraph type="secondary">{t.integrations.channelHowTo}</Typography.Paragraph>
      <Descriptions column={1} size="small">
        <Descriptions.Item label={t.integrations.channelConnected}>
          {current ?? t.integrations.channelNone}
        </Descriptions.Item>
      </Descriptions>
      <Flex wrap gap="small">
        <Button
          icon={<SendOutlined aria-hidden />}
          disabled={status.channel_id === null}
          loading={testing}
          onClick={onTest}
        >
          {t.integrations.sendTest}
        </Button>
        {connected ? (
          <Button
            aria-expanded={browse}
            onClick={() => {
              setBrowse((v) => !v);
            }}
          >
            {browse ? t.integrations.hideOther : t.integrations.findOther}
          </Button>
        ) : null}
        <Button icon={<ReloadOutlined aria-hidden />} onClick={() => void channels.refetch()}>
          {t.integrations.refresh}
        </Button>
      </Flex>
      {showList ? <Typography.Text strong>{t.integrations.detected}</Typography.Text> : null}
      {showList ? (
        <PageState query={channels}>
          {channels.data && channels.data.length > 0 ? (
            <List
              dataSource={channels.data}
              renderItem={(chat) => (
                <List.Item
                  actions={[
                    chat.chat_id === status.channel_id ? (
                      <Tag key="on" color="success">
                        {t.integrations.channelCurrent}
                      </Tag>
                    ) : (
                      <Button
                        key="connect"
                        loading={connecting}
                        onClick={() => {
                          onConnect(chat.chat_id);
                        }}
                      >
                        {t.integrations.connect}
                      </Button>
                    ),
                  ]}
                >
                  <List.Item.Meta title={chat.title} />
                </List.Item>
              )}
            />
          ) : (
            <EmptyState
              title={t.integrations.detectedEmpty}
              hint={t.integrations.detectedEmptyHint}
            />
          )}
        </PageState>
      ) : null}
    </Flex>
  );
}
