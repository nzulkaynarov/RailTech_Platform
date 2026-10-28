import { Alert, Button, Input } from "antd";
import { type ChangeEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { OffsiteBackup } from "../../../shared/api/generated/model";
import {
  useCheckOffsiteBackup,
  useGetOffsiteBackup,
  useListExternalServices,
  useSaveOffsiteBackup,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { ActionForm, ActionToggle, ErrorNote, Field, LevelTag, Masked, PanelState } from "./parts";
import { useRefreshIntegrations } from "./refresh";

/** Ссылки на консоль Google для четырёх шагов подготовки (OPS-GDRIVE-2). */
const LINKS = {
  drive: "https://drive.google.com/drive/shared-drives",
  api: "https://console.cloud.google.com/apis/library/drive.googleapis.com",
  accounts: "https://console.cloud.google.com/iam-admin/serviceaccounts",
} as const;
/** Ключ сервисного аккаунта — JSON ≈ 2,3 КБ; больше 16 КБ — точно не он (как в CRM). */
const KEY_MAX = 16384;

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

function Steps() {
  const { t } = useTranslation("integrations");
  const link = (href: string, label: string) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {label}
    </a>
  );
  return (
    <ol className="pf-int-steps" aria-label={t("storage.offsite.steps.title")}>
      <li>
        {t("storage.offsite.steps.drive")} {link(LINKS.drive, t("storage.offsite.steps.driveLink"))}
      </li>
      <li>
        {t("storage.offsite.steps.api")} {link(LINKS.api, t("storage.offsite.steps.apiLink"))}
      </li>
      <li>
        {t("storage.offsite.steps.account")}{" "}
        {link(LINKS.accounts, t("storage.offsite.steps.accountLink"))}
      </li>
      <li>{t("storage.offsite.steps.share")}</li>
    </ol>
  );
}

function SetupForm({ offsite, onDone }: { offsite: OffsiteBackup; onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const [keyText, setKeyText] = useState<string | null>(null);
  const [keyName, setKeyName] = useState("");
  const [keyProblem, setKeyProblem] = useState<string | null>(null);
  const [folder, setFolder] = useState(offsite.folder_id);
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
  const needKey = !offsite.configured || offsite.key_suffix === null;
  return (
    <ActionForm
      id="offsite"
      title={t("storage.offsite.form.title")}
      submitLabel={t("storage.offsite.form.submit")}
      pending={save.isPending}
      error={save.error}
      invalid={folder.trim() === "" || keyProblem !== null || (needKey && keyText === null)}
      consequence={[
        t("storage.offsite.form.step1"),
        t("storage.offsite.form.step2"),
        t("storage.offsite.form.step3"),
      ]}
      onCancel={onDone}
      onSubmit={(password) => {
        save.mutate({ data: { key_json: keyText, folder_id: folder.trim(), password } });
      }}
    >
      <Field
        id="offsite-key"
        label={t("storage.offsite.form.key")}
        hint={needKey ? t("storage.offsite.form.keyHint") : t("storage.offsite.form.keyKeepHint")}
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
          aria-describedby="offsite-folder-hint"
          onChange={(event) => {
            setFolder(event.target.value);
          }}
        />
      </Field>
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
      <DefinitionList
        items={[
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
          {
            label: t("storage.offsite.delivered"),
            value: offsite.delivered_at
              ? date(offsite.delivered_at, "datetime")
              : t("storage.offsite.notDelivered"),
          },
        ]}
      />
      {last ? (
        <Alert
          type={last.ok ? "success" : "warning"}
          showIcon
          role="status"
          message={t(`storage.offsite.reason.${last.reason}`, {
            folder: last.folder_name ?? "",
          })}
          description={t("storage.offsite.checkedAt", { date: date(last.checked_at, "datetime") })}
        />
      ) : null}
      {!offsite.secrets_enabled ? (
        <Alert type="warning" showIcon message={t("common.secretsOff")} />
      ) : null}
      {editable ? (
        <>
          {!offsite.configured ? <Steps /> : null}
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
            {offsite.configured ? <Steps /> : null}
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

/** «Внешняя копия бэкапов» (OPS-GDRIVE-2): ключ сервисного аккаунта Google и папка общего диска — из интерфейса,
 * без захода на сервер. Ключ только на запись: виден адрес аккаунта и последние 4 символа ID ключа. */
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
