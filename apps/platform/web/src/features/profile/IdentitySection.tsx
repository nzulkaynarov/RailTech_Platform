import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, Select, Tag } from "antd";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Language, Me, Profile } from "../../shared/api/generated/model";
import {
  getGetMeQueryKey,
  getGetProfileQueryKey,
  getGetSessionQueryKey,
  useDeleteAvatar,
  useUpdateProfile,
  useUploadAvatar,
} from "../../shared/api/generated/platform-bff";
import { LANGUAGES } from "../../shared/i18n";
import { StaffAvatar } from "../../shared/ui/StaffAvatar";
import { ContextualSaveBar } from "../../shared/ui/ContextualSaveBar";
import { AvatarCropper } from "./AvatarCropper";
import { profileErrorText } from "./errors";
import { Section } from "./Section";
import { timezoneOptions } from "./timezones";

interface Values {
  name: string;
  phone: string;
  language: Language;
  timezone: string;
  email_signature: string;
}

const ACCEPTED = ["image/png", "image/jpeg", "image/webp"];

function baselineOf(profile: Profile): Values {
  return {
    name: profile.name,
    phone: profile.phone ?? "",
    language: profile.language,
    timezone: profile.timezone,
    email_signature: profile.email_signature ?? "",
  };
}

/** Фото и личные данные: имя, телефон, язык, часовой пояс, подпись — правятся; почта, должность и роли — только чтение. */
export function IdentitySection({ me, profile }: { me: Me; profile: Profile }) {
  const { t } = useTranslation("profile");
  const { t: tShell } = useTranslation("shell");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<Values>();
  const watched = Form.useWatch([], form) as Values | undefined;
  const baseline = useMemo(() => baselineOf(profile), [profile]);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement | null>(null);

  const dirty =
    watched !== undefined &&
    (Object.keys(baseline) as (keyof Values)[]).some((k) => watched[k] !== baseline[k]);

  const refreshMe = () => {
    void queryClient.invalidateQueries({ queryKey: getGetMeQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getGetSessionQueryKey() });
  };
  const update = useUpdateProfile({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetProfileQueryKey(), next);
        // CRM нормализует значения (телефон без пробелов): форма показывает то, что сохранено.
        form.setFieldsValue(baselineOf(next));
        void message.success(t("data.saved"));
        refreshMe();
      },
    },
  });
  const upload = useUploadAvatar({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetMeQueryKey(), next);
        void queryClient.invalidateQueries({ queryKey: getGetProfileQueryKey() });
        setFile(null);
        void message.success(t("photo.saved"));
      },
    },
  });
  const remove = useDeleteAvatar({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetMeQueryKey(), next);
        void queryClient.invalidateQueries({ queryKey: getGetProfileQueryKey() });
        void message.success(t("photo.removed"));
      },
    },
  });

  const options = useMemo(() => timezoneOptions(profile.timezone), [profile.timezone]);

  const save = (values: Values) => {
    const data: Partial<Values> = {};
    for (const key of Object.keys(baseline) as (keyof Values)[]) {
      const value: string = values[key];
      if (value !== baseline[key])
        (data as Record<string, string>)[key] = key === "name" ? value.trim() : value;
    }
    if (Object.keys(data).length > 0) update.mutate({ data });
  };

  const onPick = (picked: File | undefined) => {
    if (!picked) return;
    if (!ACCEPTED.includes(picked.type)) {
      setFileError(t("photo.errors.avatar_unsupported_type"));
      return;
    }
    setFileError(null);
    setFile(picked);
  };

  const reset = () => {
    form.setFieldsValue(baseline);
    form.setFields(
      (Object.keys(baseline) as (keyof Values)[]).map((name) => ({ name, errors: [] })),
    );
    update.reset();
  };

  return (
    <Section title={t("data.title")} lead={t("lead")} testId="profile-data">
      <div className="pf-profile-identity">
        <div className="pf-profile-photo">
          <StaffAvatar initials={me.initials} src={me.avatar_url} size={96} fontSize={28} />
          <input
            ref={picker}
            type="file"
            accept={ACCEPTED.join(",")}
            className="pf-sr-only"
            aria-label={t("photo.choose")}
            tabIndex={-1}
            onChange={(event) => {
              onPick(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          <div className="pf-profile-photo-actions">
            <Button
              onClick={() => {
                picker.current?.click();
              }}
            >
              {me.avatar_url ? t("photo.change") : t("photo.choose")}
            </Button>
            {me.avatar_url ? (
              <Button
                loading={remove.isPending}
                onClick={() => {
                  remove.mutate();
                }}
              >
                {t("photo.remove")}
              </Button>
            ) : null}
          </div>
          <span className="pf-hint" style={{ maxWidth: 220 }}>
            {t("photo.hint")}
          </span>
          {fileError ? <Alert type="error" showIcon role="alert" message={fileError} /> : null}
          {remove.isError ? (
            <Alert
              type="error"
              showIcon
              role="alert"
              message={profileErrorText(t, "photo", remove.error)}
            />
          ) : null}
        </div>

        <div className="pf-profile-fields">
          {update.isError ? (
            <Alert
              type="error"
              showIcon
              role="alert"
              message={profileErrorText(t, "data", update.error)}
              style={{ marginBottom: 12 }}
            />
          ) : null}
          <dl className="pf-profile-readonly">
            <dt>{t("data.email")}</dt>
            <dd>
              {profile.email}
              <div className="pf-hint">{t("data.emailHint")}</div>
            </dd>
            <dt>{t("data.position")}</dt>
            <dd>
              {profile.position ?? t("data.noPosition")}
              <div className="pf-hint">{t("data.positionHint")}</div>
            </dd>
            <dt>{t("data.roles")}</dt>
            <dd>
              {me.roles.map((role) => (
                <Tag key={role.id}>{role.name}</Tag>
              ))}
              <div className="pf-hint">{t("data.rolesHint")}</div>
            </dd>
          </dl>
          <Form<Values>
            form={form}
            layout="vertical"
            requiredMark={false}
            initialValues={baseline}
            onFinish={save}
          >
            <Form.Item
              name="name"
              label={t("data.name")}
              rules={[{ required: true, whitespace: true, message: t("data.nameRequired") }]}
            >
              <Input autoComplete="name" maxLength={255} />
            </Form.Item>
            <Form.Item
              name="phone"
              label={t("data.phone")}
              extra={t("data.phoneHint")}
              rules={[{ pattern: /^$|^\+?[\d\s().-]{7,25}$/, message: t("data.phoneInvalid") }]}
            >
              <Input type="tel" autoComplete="tel" inputMode="tel" maxLength={40} />
            </Form.Item>
            <Form.Item name="language" label={t("data.language")}>
              <Select
                options={LANGUAGES.map((value) => ({ value, label: tShell(`languages.${value}`) }))}
              />
            </Form.Item>
            <Form.Item name="timezone" label={t("data.timezone")} extra={t("data.timezoneHint")}>
              <Select showSearch options={options} optionFilterProp="label" />
            </Form.Item>
            <Form.Item
              name="email_signature"
              label={t("data.signature")}
              extra={t("data.signatureHint")}
              rules={[{ max: 1000, message: t("data.signatureTooLong") }]}
            >
              <Input.TextArea rows={4} />
            </Form.Item>
            <ContextualSaveBar
              className="pf-profile-save-dock"
              visible={dirty}
              loading={update.isPending}
              saveLabel={t("data.save")}
              discardLabel={t("data.cancel")}
              onSave={() => {
                form.submit();
              }}
              onDiscard={reset}
            />
          </Form>
        </div>
      </div>

      <AvatarCropper
        key={file ? `${file.name}-${String(file.lastModified)}-${String(file.size)}` : "none"}
        file={file}
        saving={upload.isPending}
        error={upload.isError ? profileErrorText(t, "photo", upload.error) : null}
        onCancel={() => {
          setFile(null);
          upload.reset();
        }}
        onSave={(blob) => {
          upload.mutate({
            data: { avatar: new File([blob], "avatar.png", { type: "image/png" }) },
          });
        }}
      />
    </Section>
  );
}
