import { Alert, Button, Flex, Form, Input, Modal, Select } from "antd";
import { useState } from "react";

import type { ModelChangeIn, ModelStatus } from "../../api/generated/model";
import { ModelChangeInProvider } from "../../api/generated/model";
import { roleLabel } from "../../domain/spend";
import { t } from "../../i18n/ru";

type Provider = ModelChangeIn["provider"];
const PROVIDERS = Object.values(ModelChangeInProvider);

type Props = {
  row: ModelStatus;
  saving: boolean;
  onCancel: () => void;
  onSubmit: (body: ModelChangeIn, reset: boolean) => void;
};

const initialProvider = (row: ModelStatus): Provider =>
  PROVIDERS.find((p) => p === row.provider) ?? "anthropic";

/** Смена провайдера/модели/ключа роли (ADR-0020): ключ только на запись, подтверждение паролем. */
export function ModelChangeModal({ row, saving, onCancel, onSubmit }: Props) {
  const [provider, setProvider] = useState<Provider>(initialProvider(row));
  const [model, setModel] = useState(row.model?.split("/").slice(1).join("/") ?? "");
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [password, setPassword] = useState("");
  const role = roleLabel(row.alias);
  const body = (): ModelChangeIn => ({
    provider,
    model: model.trim(),
    api_key: apiKey.trim() || null,
    api_base: apiBase.trim() || null,
    password,
  });
  return (
    <Modal
      open
      title={t.models.editTitle.replace("{role}", role)}
      onCancel={onCancel}
      destroyOnHidden
      footer={
        <Flex wrap gap="small" justify="end">
          <Button
            disabled={!password}
            loading={saving}
            onClick={() => {
              onSubmit(body(), true);
            }}
          >
            {t.models.reset}
          </Button>
          <Button onClick={onCancel}>{t.models.cancel}</Button>
          <Button
            type="primary"
            disabled={!password || !model.trim()}
            loading={saving}
            onClick={() => {
              onSubmit(body(), false);
            }}
          >
            {t.models.save}
          </Button>
        </Flex>
      }
    >
      <Form layout="vertical" component="div">
        {row.alias === "embed-model" ? (
          <Alert
            type="warning"
            showIcon
            message={t.models.embedWarning}
            className="model-warning"
          />
        ) : null}
        {row.alias === "dialog-model" ? (
          <Alert type="info" showIcon message={t.models.dialogWarning} className="model-warning" />
        ) : null}
        <Form.Item label={t.models.providerLabel} htmlFor="model-provider">
          <Select
            id="model-provider"
            value={provider}
            options={PROVIDERS.map((p) => ({ value: p, label: t.models.providers[p] ?? p }))}
            onChange={(v: Provider) => {
              setProvider(v);
            }}
          />
        </Form.Item>
        <Form.Item
          label={t.models.modelLabel}
          htmlFor="model-id"
          extra={t.models.modelHint.replace("{examples}", t.models.examples[provider] ?? "")}
        >
          <Input
            id="model-id"
            value={model}
            autoComplete="off"
            onChange={(e) => {
              setModel(e.target.value);
            }}
          />
        </Form.Item>
        <Form.Item label={t.models.keyLabel} htmlFor="model-key" extra={t.models.keyHint}>
          <Input.Password
            id="model-key"
            value={apiKey}
            autoComplete="off"
            visibilityToggle={false}
            onChange={(e) => {
              setApiKey(e.target.value);
            }}
          />
        </Form.Item>
        <Form.Item label={t.models.baseLabel} htmlFor="model-base" extra={t.models.baseHint}>
          <Input
            id="model-base"
            value={apiBase}
            autoComplete="off"
            placeholder="https://"
            onChange={(e) => {
              setApiBase(e.target.value);
            }}
          />
        </Form.Item>
        <Form.Item
          label={t.models.passwordLabel}
          htmlFor="model-password"
          extra={t.models.passwordHint}
        >
          <Input.Password
            id="model-password"
            value={password}
            autoComplete="current-password"
            onChange={(e) => {
              setPassword(e.target.value);
            }}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
