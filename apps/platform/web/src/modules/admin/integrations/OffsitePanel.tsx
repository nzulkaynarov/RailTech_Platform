import { Alert, Button, Input, Radio } from "antd";
import { type ChangeEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { OffsiteBackup, OffsiteBackupProvider } from "../../../shared/api/generated/model";
import {
  useCheckOffsiteBackup,
  useGetOffsiteBackup,
  useListExternalServices,
  useSaveOffsiteBackup,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { hasFailedField } from "./errors";
import { ActionForm, ActionToggle, ErrorNote, Field, LevelTag, Masked, PanelState } from "./parts";
import { useRefreshIntegrations } from "./refresh";

/** Ссылки на консоль Google для четырёх шагов подготовки (OPS-GDRIVE-2). */
const LINKS = {
  drive: "https://drive.google.com/drive/shared-drives",
  api: "https://console.cloud.google.com/apis/library/drive.googleapis.com",
  accounts: "https://console.cloud.google.com/iam-admin/serviceaccounts",
  /** Пароли приложений Яндекс ID (OPS-YADISK). */
  yandexPasswords: "https://id.yandex.ru/security/app-passwords",
} as const;
/** Ключ сервисного аккаунта — JSON ≈ 2,3 КБ; больше 16 КБ — точно не он (как в CRM). */
const KEY_MAX = 16384;
const PROVIDERS: readonly OffsiteBackupProvider[] = ["yandex", "gdrive"];

/** Токен-эндпоинт Google: ключ с другим `token_uri` CRM не примет (подписанный JWT ушёл бы на чужой адрес). */
const GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token";

/** Адрес сервисного аккаунта из выбранного файла — для подтверждения админу до отправки. */
function previewEmail(text: string): string | null {
  try {
    const data: unknown = JSON.parse(text);
    if (typeof data !== "object" || data === null) return null;
    const record = data as Record<string, unknown>;
    if (record["type"] !== "service_account") return null;
    const email = record["client_email"];
    return typeof email === "string" ? email : null;
  } catch {
    return null;
  }
}

function foreignTokenUri(text: string): boolean {
  try {
    const uri = (JSON.parse(text) as Record<string, unknown>)["token_uri"];
    return uri !== undefined && uri !== GOOGLE_TOKEN_URI;
  } catch {
    return false;
  }
}

function ExternalLink({ href, label }: { href: string; label: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {label}
    </a>
  );
}

function GdriveSteps() {
  const { t } = useTranslation("integrations");
  return (
    <ol className="pf-int-steps" aria-label={t("storage.offsite.steps.title")}>
      <li>
        {t("storage.offsite.steps.drive")}{" "}
        <ExternalLink href={LINKS.drive} label={t("storage.offsite.steps.driveLink")} />
      </li>
      <li>
        {t("storage.offsite.steps.api")}{" "}
        <ExternalLink href={LINKS.api} label={t("storage.offsite.steps.apiLink")} />
      </li>
      <li>
        {t("storage.offsite.steps.account")}{" "}
        <ExternalLink href={LINKS.accounts} label={t("storage.offsite.steps.accountLink")} />
      </li>
      <li>{t("storage.offsite.steps.share")}</li>
    </ol>
  );
}

function YandexSteps() {
  const { t } = useTranslation("integrations");
  return (
    <ol className="pf-int-steps" aria-label={t("storage.offsite.yandex.steps.title")}>
      <li>{t("storage.offsite.yandex.steps.account")}</li>
      <li>
        {t("storage.offsite.yandex.steps.passwords")}{" "}
        <ExternalLink
          href={LINKS.yandexPasswords}
          label={t("storage.offsite.yandex.steps.passwordsLink")}
        />
      </li>
      <li>{t("storage.offsite.yandex.steps.files")}</li>
      <li>{t("storage.offsite.yandex.steps.paste")}</li>
    </ol>
  );
}

/** Предупреждение у Google Drive: сервисному аккаунту нужен общий диск Workspace (прод 2026-10-29). */
function WorkspaceOnly() {
  const { t } = useTranslation("integrations");
  return <Alert type="warning" showIcon role="note" message={t("storage.offsite.gdriveWarning")} />;
}

/** Поле, названное в 422 (`details.fields`): подсветка и связь с текстом ошибки формы для скринридера. */
function failedProps(error: unknown, field: string, id: string) {
  return hasFailedField(error, field)
    ? {
        status: "error" as const,
        "aria-invalid": true,
        "aria-describedby": `${id}-hint offsite-error`,
      }
    : { "aria-describedby": `${id}-hint` };
}

function SetupForm({ offsite, onDone }: { offsite: OffsiteBackup; onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const [provider, setProvider] = useState<OffsiteBackupProvider>(offsite.provider);
  // Google Drive
  const [keyText, setKeyText] = useState<string | null>(null);
  const [keyName, setKeyName] = useState("");
  const [keyProblem, setKeyProblem] = useState<string | null>(null);
  const [folder, setFolder] = useState(offsite.folder_id);
  // Яндекс Диск
  const [login, setLogin] = useState(offsite.login);
  const [folderPath, setFolderPath] = useState(offsite.folder_path || offsite.default_folder_path);
  const [appPassword, setAppPassword] = useState("");
  const save = useSaveOffsiteBackup({
    mutation: {
      onSuccess: () => {
        refresh();
        onDone();
      },
    },
  });
  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setKeyText(null);
    setKeyProblem(null);
    setKeyName(file?.name ?? "");
    if (!file) return;
    if (file.size > KEY_MAX) {
      setKeyProblem(t("storage.offsite.form.keyTooBig"));
      return;
    }
    void file.text().then((text) => {
      if (previewEmail(text) === null) {
        setKeyProblem(t("storage.offsite.form.keyNotServiceAccount"));
        return;
      }
      if (foreignTokenUri(text)) {
        setKeyProblem(t("storage.offsite.form.keyForeignTokenUri"));
        return;
      }
      setKeyText(text);
    });
  };
  const email = keyText ? previewEmail(keyText) : null;
  const yandex = provider === "yandex";
  const needKey = offsite.key_suffix === null;
  const needPassword = !offsite.app_password_configured;
  const invalid = yandex
    ? login.trim() === "" || (needPassword && appPassword.trim() === "")
    : folder.trim() === "" || keyProblem !== null || (needKey && keyText === null);
  const failed = (field: string, id: string) => failedProps(save.error, field, id);
  return (
    <ActionForm
      id="offsite"
      title={t("storage.offsite.form.title")}
      submitLabel={t("storage.offsite.form.submit")}
      pending={save.isPending}
      error={save.error}
      invalid={invalid}
      consequence={
        yandex
          ? [
              t("storage.offsite.yandex.form.step1"),
              t("storage.offsite.yandex.form.step2"),
              t("storage.offsite.yandex.form.step3"),
            ]
          : [
              t("storage.offsite.form.step1"),
              t("storage.offsite.form.step2"),
              t("storage.offsite.form.step3"),
            ]
      }
      onCancel={onDone}
      onSubmit={(password) => {
        save.mutate({
          data: yandex
            ? {
                provider: "yandex",
                login: login.trim(),
                folder_path: folderPath.trim(),
                app_password: appPassword.trim() === "" ? null : appPassword.trim(),
                password,
              }
            : { provider: "gdrive", key_json: keyText, folder_id: folder.trim(), password },
        });
      }}
    >
      <fieldset className="pf-int-fieldset">
        <legend>{t("storage.offsite.provider.label")}</legend>
        <Radio.Group
          value={provider}
          onChange={(event) => {
            setProvider(event.target.value as OffsiteBackupProvider);
          }}
        >
          {PROVIDERS.map((value) => (
            <Radio key={value} value={value}>
              {t(`storage.offsite.provider.${value}`)}
            </Radio>
          ))}
        </Radio.Group>
      </fieldset>
      {yandex ? (
        <>
          <YandexSteps />
          <Field
            id="offsite-login"
            label={t("storage.offsite.yandex.form.login")}
            hint={t("storage.offsite.yandex.form.loginHint")}
          >
            <Input
              id="offsite-login"
              type="email"
              value={login}
              autoComplete="off"
              {...failed("login", "offsite-login")}
              onChange={(event) => {
                setLogin(event.target.value);
              }}
            />
          </Field>
          <Field
            id="offsite-folder-path"
            label={t("storage.offsite.yandex.form.folder")}
            hint={t("storage.offsite.yandex.form.folderHint", {
              folder: offsite.default_folder_path,
            })}
          >
            <Input
              id="offsite-folder-path"
              value={folderPath}
              autoComplete="off"
              {...failed("folder_path", "offsite-folder-path")}
              onChange={(event) => {
                setFolderPath(event.target.value);
              }}
            />
          </Field>
          <Field
            id="offsite-app-password"
            label={t("storage.offsite.yandex.form.password")}
            hint={
              needPassword
                ? t("storage.offsite.yandex.form.passwordHint")
                : t("storage.offsite.yandex.form.passwordKeepHint")
            }
          >
            <Input.Password
              id="offsite-app-password"
              value={appPassword}
              autoComplete="new-password"
              {...failed("app_password", "offsite-app-password")}
              onChange={(event) => {
                setAppPassword(event.target.value);
              }}
            />
          </Field>
        </>
      ) : (
        <>
          <WorkspaceOnly />
          <GdriveSteps />
          <Field
            id="offsite-key"
            label={t("storage.offsite.form.key")}
            hint={
              needKey ? t("storage.offsite.form.keyHint") : t("storage.offsite.form.keyKeepHint")
            }
          >
            <input
              id="offsite-key"
              type="file"
              accept="application/json,.json"
              aria-describedby="offsite-key-hint"
              onChange={onFile}
            />
          </Field>
          {keyProblem ? (
            <Alert type="error" showIcon role="alert" message={keyProblem} />
          ) : email ? (
            <p className="pf-int-sub" role="status">
              {t("storage.offsite.form.keyChosen", { name: keyName, email })}
            </p>
          ) : null}
          <Field
            id="offsite-folder"
            label={t("storage.offsite.form.folder")}
            hint={t("storage.offsite.form.folderHint")}
          >
            <Input
              id="offsite-folder"
              value={folder}
              autoComplete="off"
              {...failed("folder_id", "offsite-folder")}
              onChange={(event) => {
                setFolder(event.target.value);
              }}
            />
          </Field>
        </>
      )}
    </ActionForm>
  );
}

function CopyState() {
  const { t } = useTranslation("integrations");
  const query = useListExternalServices();
  return (
    <PanelState query={query}>
      {(list) => {
        const row = list.items.find((service) => service.key === "offsite_backup");
        if (!row) return null;
        return (
          <div className="pf-int-form" aria-label={t("storage.offsite.copyState")}>
            <div className="pf-int-item-head">
              <span className="pf-int-item-title">{t(`health.state.${row.state}`)}</span>
              <LevelTag level={row.status} />
            </div>
            <p className="pf-int-sub">{row.summary}</p>
            {row.status !== "ok" && row.owner ? (
              <p className="pf-int-sub">
                {t("health.ownerLabel")}: {t(`health.owner.${row.owner}`)}
              </p>
            ) : null}
            {row.status !== "ok" && row.hint ? <p className="pf-int-sub">{row.hint}</p> : null}
          </div>
        );
      }}
    </PanelState>
  );
}

function Details({ offsite }: { offsite: OffsiteBackup }) {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  const delivered = {
    label: t("storage.offsite.delivered"),
    value: offsite.delivered_at
      ? date(offsite.delivered_at, "datetime")
      : t("storage.offsite.notDelivered"),
  };
  const provider = {
    label: t("storage.offsite.provider.label"),
    value: t(`storage.offsite.provider.${offsite.provider}`),
  };
  if (offsite.provider === "yandex") {
    return (
      <DefinitionList
        items={[
          provider,
          {
            label: t("storage.offsite.yandex.login"),
            value: offsite.login || t("common.notSet"),
          },
          {
            label: t("storage.offsite.yandex.folder"),
            value: offsite.folder_path || t("common.notSet"),
          },
          {
            label: t("storage.offsite.yandex.password"),
            value: <Masked configured={offsite.app_password_configured} last4={null} />,
          },
          delivered,
        ]}
      />
    );
  }
  return (
    <DefinitionList
      items={[
        provider,
        {
          label: t("storage.offsite.folder"),
          value: offsite.folder_id || t("common.notSet"),
        },
        {
          label: t("storage.offsite.account"),
          value: offsite.client_email || t("common.notSet"),
        },
        {
          label: t("storage.offsite.key"),
          value: <Masked configured={offsite.key_suffix !== null} last4={offsite.key_suffix} />,
        },
        delivered,
      ]}
    />
  );
}

function OffsiteBody({ offsite, editable }: { offsite: OffsiteBackup; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  const refresh = useRefreshIntegrations();
  const [open, setOpen] = useState(false);
  const check = useCheckOffsiteBackup({
    mutation: {
      onSuccess: () => {
        refresh();
      },
    },
  });
  const last = check.data ?? offsite.last_check;
  return (
    <div className="pf-panel-stack">
      <CopyState />
      <Details offsite={offsite} />
      {offsite.provider === "gdrive" ? <WorkspaceOnly /> : null}
      {last ? (
        <Alert
          type={last.ok ? "success" : "warning"}
          showIcon
          role="status"
          message={t(
            // Текст провайдера (`ok_yandex`, `network_yandex`, …), иначе общий по причине.
            [
              `storage.offsite.reason.${last.reason}_${offsite.provider}`,
              `storage.offsite.reason.${last.reason}`,
            ],
            { folder: last.folder_name ?? "" },
          )}
          description={t("storage.offsite.checkedAt", { date: date(last.checked_at, "datetime") })}
        />
      ) : null}
      {!offsite.secrets_enabled ? (
        <Alert type="warning" showIcon message={t("common.secretsOff")} />
      ) : null}
      {editable ? (
        <>
          <div className="pf-int-row">
            <Button
              loading={check.isPending}
              disabled={!offsite.configured}
              onClick={() => {
                check.mutate();
              }}
            >
              {t("storage.offsite.check")}
            </Button>
          </div>
          <ErrorNote error={check.error} />
          <ActionToggle
            label={t(offsite.configured ? "storage.offsite.change" : "storage.offsite.setup")}
            open={open}
            onToggle={setOpen}
          >
            <SetupForm
              offsite={offsite}
              onDone={() => {
                setOpen(false);
              }}
            />
          </ActionToggle>
        </>
      ) : (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("common.readOnly")}
        </p>
      )}
    </div>
  );
}

/** «Внешняя копия бэкапов» (OPS-GDRIVE-2, OPS-YADISK): Яндекс Диск компании (логин Яндекс 360 и пароль приложения
 * «Файлы», WebDAV) или общий диск Google Workspace (ключ сервисного аккаунта) — из интерфейса, без захода на сервер.
 * Секреты только на запись: у Яндекса виден логин и «пароль задан», у Google — адрес аккаунта и 4 символа ID ключа. */
export function OffsiteSection({ editable }: { editable: boolean }) {
  const { t } = useTranslation("integrations");
  const query = useGetOffsiteBackup();
  return (
    <section className="pf-int-block" aria-labelledby="storage-offsite-title">
      <h4 id="storage-offsite-title">{t("storage.offsite.title")}</h4>
      <p className="pf-int-sub">{t("storage.offsite.purpose")}</p>
      <PanelState query={query}>
        {(offsite) => <OffsiteBody offsite={offsite} editable={editable} />}
      </PanelState>
    </section>
  );
}
