import { Alert, App, Button, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ServiceGroup, ServiceOwner, ServiceState } from "../../../shared/api/generated/model";
import {
  checkExternalService,
  useChangeAiModel,
  useListAiModels,
  useListExternalServices,
} from "../../../shared/api/generated/platform-bff";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { copyText, mailtoLink, telegramShareLink } from "./copy";
import { STATE_TONE } from "./levels";
import { bareModelName } from "./modelName";
import { ActionForm, Field, PanelState } from "./parts";
import { useRefreshIntegrations } from "./refresh";
import { SwitchForm } from "./SwitchForm";

export function StateTag({ state }: { state: ServiceState }) {
  const { t } = useTranslation("integrations");
  return <StatusTag tone={STATE_TONE[state]}>{t(`health.state.${state}`)}</StatusTag>;
}

/** «Кто исправляет: …» — одна строка, слово из словаря; без владельца (исправлять нечего) строки нет. */
export function OwnerLine({ owner }: { owner: ServiceOwner | null }) {
  const { t } = useTranslation("integrations");
  if (owner === null) return null;
  return (
    <span>
      <span className="pf-health-label">{t("health.ownerLabel")}:</span>{" "}
      {t(`health.owner.${owner}`)}
    </span>
  );
}

/**
 * «Технические подробности»: сырой ответ провайдера или сервиса. Свёрнуты по умолчанию — человеку нужны причина, срок и
 * действие, а не текст исключения; поддержке — «Скопировать для поддержки». Секреты маскирует CRM до того, как текст
 * доходит сюда.
 */
export function TechnicalDetails({
  lines,
  context,
}: {
  lines: readonly string[];
  /** Что приложить к тексту для поддержки: сервисы, состояние, «с …» */
  context: { services: string; state: string; since: string };
}) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const regionId = useId();
  if (lines.length === 0) return null;
  const details = lines.join("\n");
  const support = t("health.technical.support", { ...context, details });
  return (
    <div className="pf-health-tech">
      <Button
        type="link"
        size="small"
        className="pf-health-tech-toggle"
        aria-expanded={open}
        aria-controls={open ? regionId : undefined}
        onClick={() => {
          setOpen(!open);
        }}
      >
        {t("health.technical.summary")}
      </Button>
      {open ? (
        <div id={regionId} className="pf-health-tech-body">
          <pre className="pf-health-pre" tabIndex={0}>
            {details}
          </pre>
          <div className="pf-int-row">
            <Button
              size="small"
              onClick={() => {
                void copyText(support).then((ok) => {
                  if (ok) void message.success(t("health.technical.copied"));
                  else void message.error(t("health.copyFailed"));
                });
              }}
            >
              {t("health.technical.copy")}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Готовый текст владельцу или хостингу: «Скопировать» и ссылки в почту и Telegram. Платформа ничего не отправляет —
 * сообщение составляет и отправляет сам сотрудник.
 */
export function WriteBox({
  who,
  text,
  headline,
}: {
  who: "owner" | "hosting";
  text: string;
  headline: string;
}) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const id = useId();
  return (
    <div
      className="pf-health-write"
      role="group"
      aria-label={t("health.write.title", { who: t(`health.write.who.${who}`) })}
    >
      <label htmlFor={id} className="pf-health-label">
        {t("health.write.label")}
      </label>
      <Input.TextArea id={id} value={text} readOnly autoSize={{ minRows: 3, maxRows: 8 }} />
      <div className="pf-int-row">
        <Button
          onClick={() => {
            void copyText(text).then((ok) => {
              if (ok) void message.success(t("health.write.copied"));
              else void message.error(t("health.copyFailed"));
            });
          }}
        >
          {t("health.write.copy")}
        </Button>
        <Button href={mailtoLink(t("health.write.mailSubject", { headline }), text)}>
          {t("health.write.mail")}
        </Button>
        <Button href={telegramShareLink(text)} target="_blank" rel="noopener noreferrer">
          {t("health.write.telegram")}
        </Button>
      </div>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("health.write.note")}
      </p>
    </div>
  );
}

/**
 * «Ввести новый ключ» прямо в строке: один ключ ложится на все роли провайдера (сохраняется зашифрованным и не
 * показывается), затем сразу проверяем провайдера. Пароль администратора — как везде, где меняются секреты.
 */
export function KeyForm({ group, onDone }: { group: ServiceGroup; onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const vendorKey = group.service_keys.find((key) => key.startsWith("vendor."));
  const provider = vendorKey?.slice("vendor.".length) ?? "";
  const models = useListAiModels();
  const change = useChangeAiModel();
  const [key, setKey] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string[] | null>(null);
  const roles = (models.data?.items ?? []).filter((model) => model.provider === provider);
  const roleNames = roles.map((model) =>
    t(`models.alias.${model.alias}`, { defaultValue: model.alias }),
  );
  const submit = async (password: string) => {
    setPending(true);
    setError(null);
    try {
      for (const model of roles) {
        await change.mutateAsync({
          alias: model.alias,
          data: {
            provider: provider as "anthropic" | "gemini" | "openai",
            model: bareModelName(model.provider, model.model),
            api_key: key,
            password,
          },
        });
      }
      if (vendorKey) await checkExternalService(vendorKey).catch(() => undefined);
      setDone(roleNames);
      setKey("");
      refresh();
    } catch (failure) {
      setError(failure);
    } finally {
      setPending(false);
    }
  };
  return (
    <PanelState query={models}>
      {() =>
        roles.length === 0 ? (
          <Alert type="info" showIcon message={t("health.key.noRoles")} />
        ) : done ? (
          <Alert
            type="success"
            showIcon
            role="status"
            message={t("health.key.done", { roles: done.join(", ") })}
          />
        ) : (
          <ActionForm
            id={`key-${group.id}`}
            title={t("health.key.title", {
              vendor: t(`models.provider.${provider}`, { defaultValue: provider }),
            })}
            submitLabel={t("health.key.submit")}
            pending={pending}
            error={error}
            invalid={key.length < 8}
            consequence={[t("health.key.step1"), t("health.key.step2"), t("health.key.step3")]}
            onCancel={onDone}
            onSubmit={(password) => {
              void submit(password);
            }}
          >
            <Field
              id={`key-${group.id}-value`}
              label={t("health.key.label")}
              hint={t("health.key.hint", { roles: roleNames.join(", ") })}
            >
              <Input
                id={`key-${group.id}-value`}
                type="password"
                autoComplete="off"
                value={key}
                onChange={(event) => {
                  setKey(event.target.value);
                }}
              />
            </Field>
          </ActionForm>
        )
      }
    </PanelState>
  );
}

/** «Выключить провайдера»: та же форма с паролем и блоком «Что произойдёт», что в карточке «Внешние сервисы». */
export function ProviderSwitch({ group, onDone }: { group: ServiceGroup; onDone: () => void }) {
  const list = useListExternalServices();
  const vendorKey =
    group.service_keys.find((key) => key.startsWith("vendor.")) ?? group.service_keys[0];
  return (
    <PanelState query={list}>
      {(data) => {
        const service = data.items.find((item) => item.key === vendorKey);
        return service ? <SwitchForm service={service} onDone={onDone} /> : null;
      }}
    </PanelState>
  );
}
