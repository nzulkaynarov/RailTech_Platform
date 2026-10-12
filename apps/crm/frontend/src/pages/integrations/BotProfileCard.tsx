import { Alert, App as AntApp, Button, Form, Input, Tabs, Tag, Typography } from "antd";

import type { BotProfileOut, BotProfileSettings } from "../../api/generated/model";
import { useBotProfile, useSaveBotProfile } from "../../api/templateQueries";
import { PageState } from "../../components/PageState";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { publishText } from "../../domain/botProfile";
import "../admin.css";

const tt = t.botProfile;
const FIELDS = [
  { key: "name", label: tt.name, max: 64, area: false },
  { key: "description", label: tt.description, max: 512, area: true },
  { key: "short_description", label: tt.shortDescription, max: 120, area: true },
] as const;
const LANGUAGES = ["ru", "uz", "en"] as const;

function PublishStatus({ published }: { published: BotProfileOut["published"] }) {
  const state = publishText(published);
  if (state.ok) {
    return (
      <Typography.Paragraph>
        <Tag color="success">{tt.published}</Tag> {state.text}
      </Typography.Paragraph>
    );
  }
  return (
    <Alert type={published ? "warning" : "info"} showIcon message={state.text} role="status" />
  );
}

/** Вкладка «Профиль бота»: имя и описания на ru/uz/en — вкладками языков (ADR-0018); сохранение публикует их в Telegram. */
export function BotProfileCard() {
  const profile = useBotProfile();
  const save = useSaveBotProfile(useApiErrorToast());
  const { message } = AntApp.useApp();
  return (
    <PageState query={profile} variant="section">
      {profile.data ? (
        <Form<BotProfileSettings>
          layout="vertical"
          initialValues={profile.data.profile}
          onFinish={(values) => {
            save.mutate(values, { onSuccess: () => void message.success(tt.saved) });
          }}
        >
          <Typography.Paragraph type="secondary">{tt.intro}</Typography.Paragraph>
          <PublishStatus published={profile.data.published} />
          <Tabs
            size="small"
            aria-label={tt.languages}
            items={LANGUAGES.map((language) => ({
              key: language,
              label: tt[language],
              // Все языки в форме сразу: иначе «Сохранить» не отправит поля неоткрытых вкладок.
              forceRender: true,
              children: FIELDS.map((field) => (
                <Form.Item
                  key={field.key}
                  name={[field.key, language]}
                  label={field.label}
                  htmlFor={`bot-${field.key}-${language}`}
                >
                  {field.area ? (
                    <Input.TextArea
                      id={`bot-${field.key}-${language}`}
                      autoSize={{ minRows: 2, maxRows: 6 }}
                      maxLength={field.max}
                      showCount
                    />
                  ) : (
                    <Input id={`bot-${field.key}-${language}`} maxLength={field.max} showCount />
                  )}
                </Form.Item>
              )),
            }))}
          />
          <Button type="primary" htmlType="submit" loading={save.isPending}>
            {tt.save}
          </Button>
        </Form>
      ) : null}
    </PageState>
  );
}
