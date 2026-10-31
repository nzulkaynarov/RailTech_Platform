import { Alert, Button, Input, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AiModel, AiModelChange } from "../../../shared/api/generated/model";
import {
  useChangeAiModel,
  useListAiModels,
  useResetAiModel,
  useTestAiModel,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { hasFailedField } from "./errors";
import { TechnicalDetails } from "./HealthParts";
import { bareModelName } from "./modelName";
import { ActionForm, ErrorNote, Field, Masked, PanelState, PanelTitle } from "./parts";
import { useRefreshIntegrations } from "./refresh";

const PROVIDERS = ["anthropic", "gemini", "openai"] as const;
type Provider = (typeof PROVIDERS)[number];

function ChangeResult({ result }: { result: AiModelChange }) {
  const { t } = useTranslation("integrations");
  return (
    <div className="pf-int-form">
      <Alert
        type="success"
        showIcon
        role="status"
        message={t("models.change.done", { model: `${result.provider} · ${result.model}` })}
        description={t(`models.keySource.${result.key_source}`)}
      />
      {result.reindex_required ? (
        <Alert type="warning" showIcon role="status" message={t("models.change.reindex")} />
      ) : null}
      {result.quality_check_recommended ? (
        <Alert type="info" showIcon role="status" message={t("models.change.quality")} />
      ) : null}
    </div>
  );
}

function ChangeForm({ model, onDone }: { model: AiModel; onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const known = (PROVIDERS as readonly string[]).includes(model.provider ?? "");
  const [provider, setProvider] = useState<Provider>(
    known ? (model.provider as Provider) : "anthropic",
  );
  // Имя у провайдера без префикса «провайдер/»: в поле не показываем то, что CRM пришлось бы нормализовать.
  const [name, setName] = useState(bareModelName(model.provider, model.model));
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState("");
  const change = useChangeAiModel({
    mutation: {
      onSuccess: () => {
        refresh();
      },
    },
  });
  const id = `model-${model.alias}`;
  // Поля, названные в 422: подсвечиваем и связываем с текстом ошибки (`${id}-error`), чтобы скринридер его прочёл.
  const failed = (field: string, hint: string) =>
    hasFailedField(change.error, field)
      ? {
          status: "error" as const,
          "aria-invalid": true,
          "aria-describedby": `${id}-${hint}-hint ${id}-error`,
        }
      : {};
  return (
    <div className="pf-int-form">
      <ActionForm
        id={id}
        title={t("models.change.title", {
          alias: t(`models.alias.${model.alias}`, { defaultValue: model.alias }),
        })}
        submitLabel={t("models.change.submit")}
        pending={change.isPending}
        error={change.error}
        invalid={name.trim() === "" || (apiKey !== "" && apiKey.length < 8)}
        consequence={[
          t("models.change.step1"),
          apiKey ? t("models.change.step2Key") : t("models.change.step2Env"),
          t("models.change.step3"),
        ]}
        onCancel={onDone}
        onSubmit={(password) => {
          change.mutate({
            alias: model.alias,
            data: {
              provider,
              model: name.trim(),
              ...(apiKey ? { api_key: apiKey } : {}),
              ...(apiBase.trim() ? { api_base: apiBase.trim() } : {}),
              password,
            },
          });
        }}
      >
        <Field id={`${id}-provider`} label={t("models.change.provider")}>
          <Select
            id={`${id}-provider`}
            value={provider}
            options={PROVIDERS.map((value) => ({ value, label: t(`models.provider.${value}`) }))}
            onChange={setProvider}
          />
        </Field>
        <Field
          id={`${id}-name`}
          label={t("models.change.model")}
          hint={t("models.change.modelHint", {
            provider,
            example: t(`models.change.example.${provider}`),
          })}
        >
          <Input
            id={`${id}-name`}
            value={name}
            autoComplete="off"
            {...failed("model", "name")}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </Field>
        <Field id={`${id}-key`} label={t("models.change.key")} hint={t("models.change.keyHint")}>
          <Input
            id={`${id}-key`}
            type="password"
            autoComplete="off"
            value={apiKey}
            {...failed("api_key", "key")}
            onChange={(event) => {
              setApiKey(event.target.value);
            }}
          />
        </Field>
        <Field id={`${id}-base`} label={t("models.change.base")} hint={t("models.change.baseHint")}>
          <Input
            id={`${id}-base`}
            value={apiBase}
            autoComplete="off"
            {...failed("api_base", "base")}
            onChange={(event) => {
              setApiBase(event.target.value);
            }}
          />
        </Field>
      </ActionForm>
      {change.data ? <ChangeResult result={change.data} /> : null}
    </div>
  );
}

function ResetForm({ model, onDone }: { model: AiModel; onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const reset = useResetAiModel({
    mutation: {
      onSuccess: () => {
        refresh();
      },
    },
  });
  return (
    <div className="pf-int-form">
      <ActionForm
        id={`model-reset-${model.alias}`}
        title={t("models.reset.title", {
          alias: t(`models.alias.${model.alias}`, { defaultValue: model.alias }),
        })}
        submitLabel={t("models.reset.submit")}
        danger
        pending={reset.isPending}
        error={reset.error}
        consequence={[t("models.reset.step1"), t("models.reset.step2"), t("models.reset.step3")]}
        onCancel={onDone}
        onSubmit={(password) => {
          reset.mutate({ alias: model.alias, data: { password } });
        }}
      />
      {reset.data ? <ChangeResult result={reset.data} /> : null}
    </div>
  );
}

function ModelRow({ model, editable }: { model: AiModel; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const { date, money } = useFormat();
  const refresh = useRefreshIntegrations();
  const [form, setForm] = useState<"test" | "change" | "reset" | null>(null);
  const test = useTestAiModel({
    mutation: {
      onSuccess: () => {
        refresh();
      },
    },
  });
  const title = t(`models.alias.${model.alias}`, { defaultValue: model.alias });
  return (
    <li>
      <div className="pf-int-item-head">
        <span className="pf-int-item-title">{title}</span>
        <StatusTag kind="modelHealth" status={model.health}>
          {t(`models.health.${model.health}`)}
        </StatusTag>
      </div>
      <p className="pf-int-sub">
        {model.provider
          ? `${model.provider} · ${bareModelName(model.provider, model.model) || "—"}`
          : t("models.notSet")}
        {" · "}
        {t("models.today", {
          amount: money(model.today_usd, { currency: "USD", fractionDigits: 2 }),
        })}
      </p>
      {model.health === "problem" ? (
        <p className="pf-int-sub">{t("health.model.problem", { alias: title })}</p>
      ) : null}
      {model.health_detail ? (
        <TechnicalDetails
          lines={[model.health_detail]}
          context={{ services: title, state: t("models.health.problem"), since: "" }}
        />
      ) : null}
      <p className="pf-int-sub">
        {t("models.key.label")}{" "}
        {model.key_source === "crm" ? (
          <>
            <Masked configured last4={model.key_last4} /> {t("models.key.crm")}
          </>
        ) : (
          t(model.key_source === "env" ? "models.key.env" : "models.key.unknown")
        )}
      </p>
      <p className="pf-int-sub">
        {model.checked_at
          ? t("models.checkedAt", { date: date(model.checked_at, "datetime") })
          : t("models.neverChecked")}
      </p>
      {editable ? (
        <div className="pf-int-row">
          <Button
            size="small"
            aria-label={t("models.test.aria", { alias: title })}
            aria-expanded={form === "test"}
            onClick={() => {
              setForm(form === "test" ? null : "test");
            }}
          >
            {t("common.check")}
          </Button>
          <Button
            size="small"
            aria-expanded={form === "change"}
            aria-label={t("models.change.aria", { alias: title })}
            onClick={() => {
              setForm(form === "change" ? null : "change");
            }}
          >
            {t("models.change.button")}
          </Button>
          <Button
            size="small"
            danger
            aria-expanded={form === "reset"}
            aria-label={t("models.reset.aria", { alias: title })}
            onClick={() => {
              setForm(form === "reset" ? null : "reset");
            }}
          >
            {t("models.reset.button")}
          </Button>
        </div>
      ) : null}
      {test.data ? (
        <Alert
          type={test.data.ok ? "success" : "error"}
          showIcon
          role="status"
          message={t(test.data.ok ? "models.test.ok" : "models.test.fail", { alias: title })}
          description={[
            t("models.test.latency", { ms: test.data.latency_ms }),
            test.data.cost_usd !== null
              ? t("models.test.cost", {
                  amount: money(test.data.cost_usd, { currency: "USD", fractionDigits: 4 }),
                })
              : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        />
      ) : null}
      {test.data?.detail ? (
        <TechnicalDetails
          lines={[test.data.detail]}
          context={{ services: title, state: t("models.test.fail", { alias: title }), since: "" }}
        />
      ) : null}
      <ErrorNote error={test.error} />
      {form === "test" ? (
        <ActionForm
          id={`model-test-${model.alias}`}
          title={t("models.test.confirm.title", { alias: title })}
          submitLabel={t("models.test.confirm.submit")}
          needsPassword={false}
          pending={test.isPending}
          error={null}
          consequence={[t("models.test.confirm.step1"), t("models.test.confirm.step2")]}
          onCancel={() => {
            setForm(null);
          }}
          onSubmit={() => {
            test.mutate(
              { alias: model.alias },
              {
                onSettled: () => {
                  setForm(null);
                },
              },
            );
          }}
        />
      ) : null}
      {form === "change" ? (
        <ChangeForm
          model={model}
          onDone={() => {
            setForm(null);
          }}
        />
      ) : null}
      {form === "reset" ? (
        <ResetForm
          model={model}
          onDone={() => {
            setForm(null);
          }}
        />
      ) : null}
    </li>
  );
}

/** Карточка «Модели ИИ»: алиасы, провайдер и модель, ключ (ввод, не показывается), «Проверить», «Сменить», «Сбросить». */
export function ModelsPanel({ editable }: { editable: boolean }) {
  const { t } = useTranslation("integrations");
  const query = useListAiModels();
  return (
    <div className="pf-panel-stack">
      <PanelTitle>{t("cards.models.title")}</PanelTitle>
      {editable ? null : (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("common.readOnly")}
        </p>
      )}
      <PanelState query={query}>
        {(list) =>
          list.items.length === 0 ? (
            <p className="pf-hint" style={{ margin: 0 }}>
              {t("models.empty")}
            </p>
          ) : (
            <ul className="pf-int-list" aria-label={t("cards.models.title")}>
              {list.items.map((model) => (
                <ModelRow key={model.alias} model={model} editable={editable} />
              ))}
            </ul>
          )
        }
      </PanelState>
    </div>
  );
}
