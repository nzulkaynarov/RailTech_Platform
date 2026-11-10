import {
  ChatContainer,
  ConversationHeader,
  MainContainer,
  MessageInput,
  MessageList,
  Search,
  Sidebar,
} from "@chatscope/chat-ui-kit-react";
import "@chatscope/chat-ui-kit-styles/dist/default/styles.min.css";
import { useTranslation } from "react-i18next";

import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { SoonButton } from "../../../shared/ui/SoonButton";
import "./chats.css";

const GROUPS = ["objects", "direct"] as const;

/** Органайзер · Чаты: раскладка на готовых компонентах; переписка подключается отдельным этапом. */
export function ChatsPage() {
  const { t } = useTranslation(["modules"]);
  const title = t("modules:chats.sections.all");
  useDocumentTitle(title);
  const noData = t("modules:chats.inbox.noData");

  return (
    <div className="pf-chats">
      <PageHeader title={title} extra={<SoonButton>{t("modules:chats.inbox.call")}</SoonButton>} />
      <MainContainer>
        <Sidebar position="left">
          <Search placeholder={t("modules:chats.inbox.search")} disabled />
          {GROUPS.map((group) => (
            <section key={group} aria-labelledby={`pf-chats-${group}`} className="pf-chats-group">
              <h2 id={`pf-chats-${group}`}>{t(`modules:chats.inbox.groups.${group}`)}</h2>
              <p className="pf-hint">{noData}</p>
            </section>
          ))}
        </Sidebar>
        <ChatContainer>
          <ConversationHeader>
            <ConversationHeader.Content userName={title} />
          </ConversationHeader>
          <MessageList>
            <MessageList.Content className="pf-chats-empty">{noData}</MessageList.Content>
          </MessageList>
          <MessageInput
            placeholder={t("modules:chats.inbox.message")}
            attachButton={false}
            disabled
            sendButton={false}
          />
        </ChatContainer>
      </MainContainer>
    </div>
  );
}
