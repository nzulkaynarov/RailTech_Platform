import { Alert, App, Button, Input, Segmented } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  BotProfile,
  BotProfileState,
  TelegramChannel,
  TelegramConnector,
} from "../../../shared/api/generated/model";
import {
  useConnectTelegramChannel,
  useGetBotProfile,
  useGetTelegramConnector,
  useListTelegramChannels,
  useSaveBotProfile,
  useSetTelegramToken,
  useTestTelegramChannel,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusTag } from "../../../shared/ui/StatusTag";
import {
  ActionForm,
  ActionToggle,
  ErrorNote,
  Field,
  Masked,
  PanelState,
  PanelTitle,
} from "./parts";
import { TechnicalDetails } from "./HealthParts";
import { useRefreshIntegrations } from "./refresh";

const LANGS = ["ru", "uz", "en"] as const;
const LIMITS = { name: 64, short_description: 120, description: 512 } as const;
type ProfileField = keyof typeof LIMITS;

function TokenForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const refresh = useRefreshIntegrations();
  const [token, setToken] = useState("");
  const save = useSetTelegramToken({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("telegram.token.saved"));
        onDone();
      },
    },
  });
  return (
    <ActionForm
      id="tg-token"
      title={t("telegram.token.title")}
      submitLabel={t("telegram.token.submit")}
      pending={save.isPending}
      error={save.error}
      invalid={token.trim().length < 20}
      consequence={[
        t("telegram.token.step1"),
        t("telegram.token.step2"),
        t("telegram.token.step3"),
      ]}
      onCancel={onDone}
      onSubmit={(password) => {
        save.mutate({ data: { token: token.trim(), password } });
      }}
    >
      <Field id="tg-token-value" label={t("telegram.token.label")} hint={t("telegram.token.hint")}>
        <Input
          id="tg-token-value"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(event) => {
            setToken(event.target.value);
          }}
        />
      </Field>
    </ActionForm>
  );
}

function ChannelBlock({ bot, editable }: { bot: TelegramConnector; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const { date } = useFormat();
  const refresh = useRefreshIntegrations();
  const channels = useListTelegramChannels({ query: { enabled: bot.configured } });
  const connect = useConnectTelegramChannel({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("telegram.channel.connected"));
      },
    },
  });
  const test = useTestTelegramChannel({
    mutation: {
      onSuccess: () => {
        void message.success(t("telegram.channel.testSent"));
      },
    },
  });
  const items: TelegramChannel[] = channels.data?.items ?? [];
  return (
    <section className="pf-int-block" aria-labelledby="tg-channel-title">
      <h4 id="tg-channel-title">{t("telegram.channel.title")}</h4>
      <p className="pf-int-sub">
        {bot.channel_title
          ? t("telegram.channel.current", { title: bot.channel_title })
          : t("telegram.channel.none")}
      </p>
      {editable && bot.channel_id !== null ? (
        <div className="pf-int-row">
          <Button
            loading={test.isPending}
            onClick={() => {
              test.mutate();
            }}
          >
            {t("telegram.channel.test")}
          </Button>
        </div>
      ) : null}
      <ErrorNote error={test.error} />
      {bot.configured ? (
        items.length === 0 ? (
          <p className="pf-hint" style={{ margin: 0 }}>
            {t("telegram.channel.empty")}
          </p>
        ) : (
          <ul className="pf-int-list" aria-label={t("telegram.channel.candidates")}>
            {items.map((channel) => (
              <li key={channel.chat_id}>
                <div className="pf-int-item-head">
                  <span className="pf-int-item-title">{channel.title}</span>
                  {channel.chat_id === bot.channel_id ? (
                    <StatusTag tone="green">{t("telegram.channel.isCurrent")}</StatusTag>
                  ) : editable ? (
                    <Button
                      size="small"
                      loading={connect.isPending}
                      aria-label={t("telegram.channel.connectAria", { title: channel.title })}
                      onClick={() => {
                        connect.mutate({ chatId: channel.chat_id });
                      }}
                    >
                      {t("telegram.channel.connect")}
                    </Button>
                  ) : null}
                </div>
                <p className="pf-int-sub">
                  {t("telegram.channel.detected", { date: date(channel.detected_at, "datetime") })}
                </p>
              </li>
            ))}
          </ul>
        )
      ) : null}
      <ErrorNote error={connect.error} />
    </section>
  );
}

type ProfileDraft = Record<ProfileField, Record<(typeof LANGS)[number], string>>;

function draftOf(profile: BotProfile): ProfileDraft {
  return {
    name: { ...profile.name },
    short_description: { ...profile.short_description },
    description: { ...profile.description },
  };
}

function ProfileForm({ state, editable }: { state: BotProfileState; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const { date } = useFormat();
  const refresh = useRefreshIntegrations();
  const [draft, setDraft] = useState<ProfileDraft>(() => draftOf(state.profile));
  const [activeLang, setActiveLang] = useState<(typeof LANGS)[number]>("ru");
  const save = useSaveBotProfile({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("telegram.profile.saved"));
      },
    },
  });
  const tooLong = (Object.keys(LIMITS) as ProfileField[]).some((field) =>
    LANGS.some((lang) => draft[field][lang].length > LIMITS[field]),
  );
  const set = (field: ProfileField, lang: (typeof LANGS)[number], value: string) => {
    setDraft((prev) => ({ ...prev, [field]: { ...prev[field], [lang]: value } }));
  };
  const published = state.published;
  return (
    <section className="pf-int-block" aria-labelledby="tg-profile-title">
      <h4 id="tg-profile-title">{t("telegram.profile.title")}</h4>
      {published ? (
        <p className="pf-int-sub">
          {published.ok
            ? t("telegram.profile.publishedOk", { date: date(published.at, "datetime") })
            : t(`telegram.profile.publishError.${published.error ?? "telegram_error"}`, {
                seconds: published.retry_after ?? 0,
              })}
        </p>
      ) : null}
      <form
        className="pf-int-form"
        aria-label={t("telegram.profile.title")}
        onSubmit={(event) => {
          event.preventDefault();
          if (!editable || tooLong) return;
          save.mutate({
            data: {
              name: draft.name,
              short_description: draft.short_description,
              description: draft.description,
            },
          });
        }}
      >
        <div style={{ marginBottom: 12 }}>
          <Segmented<(typeof LANGS)[number]>
            aria-label={t("telegram.profile.title")}
            value={activeLang}
            onChange={setActiveLang}
            options={LANGS.map((lang) => ({
              value: lang,
              label: t(`telegram.profile.lang.${lang}`),
            }))}
          />
        </div>
        <div className="pf-int-form">
          {(["name", "short_description", "description"] as const).map((field) => {
            const id = `tg-profile-${field}-${activeLang}`;
            const over = draft[field][activeLang].length > LIMITS[field];
            const Control = field === "description" ? Input.TextArea : Input;
            return (
              <Field
                key={field}
                id={id}
                label={t(`telegram.profile.fields.${field}`)}
                hint={t("telegram.profile.counter", {
                  count: draft[field][activeLang].length,
                  max: LIMITS[field],
                })}
              >
                <Control
                  id={id}
                  value={draft[field][activeLang]}
                  readOnly={!editable}
                  status={over ? "error" : undefined}
                  aria-describedby={`${id}-hint`}
                  onChange={(event) => {
                    set(field, activeLang, event.target.value);
                  }}
                  {...(field === "description" ? { rows: 4 } : {})}
                />
              </Field>
            );
          })}
        </div>
        {tooLong ? (
          <Alert type="error" showIcon role="alert" message={t("telegram.profile.tooLong")} />
        ) : null}
        <ErrorNote error={save.error} />
        {editable ? (
          <div className="pf-int-row">
            <Button htmlType="submit" loading={save.isPending} disabled={tooLong}>
              {t("telegram.profile.submit")}
            </Button>
          </div>
        ) : null}
      </form>
    </section>
  );
}

/** Где настраивается бот целиком (W15-H4): Настройки · Telegram-бот, вкладка «Подключение». */
export const BOT_CONNECTION_PATH = "/admin/bot?part=connection";

function TelegramBody({
  bot,
  editable,
  summary,
  initialTokenOpen,
}: {
  bot: TelegramConnector;
  editable: boolean;
  summary: boolean;
  initialTokenOpen: boolean;
}) {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  const [tokenOpen, setTokenOpen] = useState(initialTokenOpen && editable && !bot.configured);
  const profile = useGetBotProfile({ query: { enabled: bot.configured && !summary } });
  return (
    <div className="pf-panel-stack">
      <DefinitionList
        items={[
          { label: t("telegram.bot"), value: bot.username ? `@${bot.username}` : null },
          {
            label: t("telegram.running"),
            value: !bot.configured
              ? t("telegram.runningValue.none")
              : bot.running
                ? t("telegram.runningValue.yes")
                : t("telegram.runningValue.no"),
          },
          {
            label: t("telegram.token.current"),
            value: <Masked configured={bot.configured} last4={bot.last4} />,
          },
          {
            label: t("telegram.updated"),
            value: bot.updated_at ? date(bot.updated_at, "datetime") : null,
          },
          {
            label: t("telegram.lastError"),
            value: bot.last_error ? (
              <>
                {t(`telegram.lastErrorCode.${bot.last_error}`, { defaultValue: "" })}
                <TechnicalDetails
                  lines={[bot.last_error]}
                  context={{
                    services: t("cards.telegram.title"),
                    state: t("telegram.lastError"),
                    since: "",
                  }}
                />
              </>
            ) : null,
          },
        ]}
      />
      {!bot.secrets_enabled ? (
        <Alert type="warning" showIcon message={t("common.secretsOff")} />
      ) : null}
      {summary ? (
        <div>
          <LinkButton type="primary" to={BOT_CONNECTION_PATH}>
            {t(editable ? "telegram.configureBot" : "telegram.viewBot")}
          </LinkButton>
        </div>
      ) : null}
      {summary ? null : editable ? (
        <ActionToggle
          label={bot.configured ? t("telegram.token.change") : t("telegram.token.set")}
          open={tokenOpen}
          onToggle={setTokenOpen}
        >
          <TokenForm
            onDone={() => {
              setTokenOpen(false);
            }}
          />
        </ActionToggle>
      ) : (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("common.readOnly")}
        </p>
      )}
      {summary ? null : <ChannelBlock bot={bot} editable={editable} />}
      {bot.configured && !summary ? (
        <PanelState query={profile}>
          {(state) => <ProfileForm state={state} editable={editable} />}
        </PanelState>
      ) : null}
    </div>
  );
}

/**
 * Подключение Telegram-бота: токен (ввод, маска), канал команды (список, подключить, тест), профиль бота. Целиком — на
 * вкладке «Подключение» в Настройках · Telegram-бот и в шаге мастера (`initialTokenOpen` — форма токена сразу открыта,
 * пока токена нет); в «Подключениях» — кратко (`summary`): состояние и «Настроить бота» (W15-H4).
 */
export function TelegramPanel({
  editable,
  summary = false,
  initialTokenOpen = false,
}: {
  editable: boolean;
  summary?: boolean;
  initialTokenOpen?: boolean;
}) {
  const { t } = useTranslation("integrations");
  const query = useGetTelegramConnector();
  return (
    <div className="pf-panel-stack">
      <PanelTitle>{t("cards.telegram.title")}</PanelTitle>
      <PanelState query={query}>
        {(bot) => (
          <TelegramBody
            bot={bot}
            editable={editable}
            summary={summary}
            initialTokenOpen={initialTokenOpen}
          />
        )}
      </PanelState>
    </div>
  );
}
