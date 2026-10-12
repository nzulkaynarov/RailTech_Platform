import { Alert, App as AntApp, Button, Card, Form, Input, Tag, Typography } from "antd";

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

/** Имя и описания бота на ru/uz/en (ADR-0018): сохранение публикует их в Telegram. */
export function BotProfileCard() {
  const profile = useBotProfile();
  const save = useSaveBotProfile(useApiErrorToast());
  const { message } = AntApp.useApp();
  return (
    <Card title={tt.title}>
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
            {FIELDS.map((field) => (
              <fieldset key={field.key} className="bot-profile-group">
                <legend>{field.label}</legend>
                {LANGUAGES.map((language) => (
                  <Form.Item
                    key={language}
                    name={[field.key, language]}
                    label={tt[language]}
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
                ))}
              </fieldset>
            ))}
            <Button type="primary" htmlType="submit" loading={save.isPending}>
              {tt.save}
            </Button>
          </Form>
        ) : null}
      </PageState>
    </Card>
  );
}
