import { Col, Form, Input, InputNumber, Row, Select, Switch, Typography } from "antd";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { fieldLabel } from "./fieldLabel";
import { type JsonSchema, bounds, kindOf, resolve } from "./schemaForm";
import { fillPlaceholders, hasPlaceholders, isShortField, widgetFor } from "./sections";
import { SettingsWidget } from "./widgets";

type NamePath = (string | number)[];

interface Props {
  name: NamePath;
  schema: JsonSchema;
  root: JsonSchema;
  label: string;
  /** Подстановки для предпросмотра текстов: `{company}`, `{hours}`… */
  samples: Record<string, string>;
}

const lastKey = (name: NamePath) => String(name[name.length - 1] ?? "");

function enumOptions(t: TFunction, values: unknown[] | undefined) {
  return (values ?? []).map((v) => ({
    value: String(v),
    label: t(`bot:options.${String(v)}`, { defaultValue: String(v) }),
  }));
}

/** Предпросмотр текста с подстановками: показывается, только если в тексте есть `{…}`. */
export function Preview({ name, samples }: { name: NamePath; samples: Record<string, string> }) {
  const { t } = useTranslation("bot");
  const text = String(Form.useWatch(name, { preserve: true }) ?? "");
  if (!hasPlaceholders(text)) return null;
  return (
    <Typography.Paragraph type="secondary" className="pf-bot-preview">
      {t("texts.preview")}: {fillPlaceholders(text, samples)}
    </Typography.Paragraph>
  );
}

/** Три поля ru/uz/en друг под другом с предпросмотром — редактор текста бота. */
export function LocalizedFields({ name, label: title, samples }: Omit<Props, "schema" | "root">) {
  const { t } = useTranslation(["bot", "kb"]);
  return (
    <>
      {(["ru", "uz", "en"] as const).map((lang) => (
        <div key={lang}>
          <Form.Item
            name={[...name, lang]}
            label={t(`kb:languages.${lang}`)}
            rules={[{ required: true, whitespace: true, message: t("bot:texts.emptyTranslation") }]}
          >
            <Input.TextArea
              aria-label={`${title} · ${t(`kb:languages.${lang}`)}`}
              autoSize={{ minRows: 3, maxRows: 10 }}
            />
          </Form.Item>
          <Preview name={[...name, lang]} samples={samples} />
        </div>
      ))}
    </>
  );
}

function control(t: TFunction, key: string, s: JsonSchema, label: string) {
  const format = s.type === "array" ? s.items?.format : s.format;
  const widget = widgetFor(key, format ? { format } : {});
  if (widget) return <SettingsWidget widget={widget} label={label} />;
  switch (kindOf(s)) {
    case "boolean":
      return <Switch />;
    case "integer":
    case "number": {
      const unit = t(`bot:units.${key}`, { defaultValue: "" });
      return (
        <InputNumber
          style={{ width: "100%", maxWidth: 240 }}
          step={kindOf(s) === "integer" ? 1 : 0.05}
          {...(unit ? { suffix: unit } : {})}
          {...bounds(s)}
        />
      );
    }
    case "tags":
    case "number-tags":
      return <Select mode="tags" tokenSeparators={[","]} open={false} suffixIcon={null} />;
    case "enum":
      return <Select options={enumOptions(t, s.enum)} />;
    case "multi-enum":
      return <Select mode="multiple" options={enumOptions(t, s.items?.enum)} />;
    default:
      return s.description && s.description.length > 80 ? <Input.TextArea autoSize /> : <Input />;
  }
}

/** Поле формы настроек по JSON Schema Pydantic CRM (рекурсивно для вложенных объектов). */
export function SchemaField({ name, schema, root, label: title, samples }: Props) {
  const { t } = useTranslation(["bot", "kb"]);
  const { schema: s } = resolve(schema, root);
  const kind = kindOf(s);
  if (kind === "localized") return <LocalizedFields name={name} label={title} samples={samples} />;
  if (kind === "object") {
    const fields = (
      <Row gutter={16}>
        {Object.entries(s.properties ?? {}).map(([key, child]) => (
          <Col key={key} xs={24} lg={isShortField(key, resolve(child, root).schema) ? 12 : 24}>
            <SchemaField
              name={[...name, key]}
              schema={child}
              root={root}
              label={fieldLabel(t, key, child)}
              samples={samples}
            />
          </Col>
        ))}
      </Row>
    );
    // Вложенная группа (лимиты по провайдерам) — с названием; корень раздела — без.
    return name.length === 0 ? (
      fields
    ) : (
      <fieldset className="pf-bot-group">
        <legend>{title}</legend>
        {fields}
      </fieldset>
    );
  }
  const key = lastKey(name);
  return (
    <Form.Item
      name={name}
      label={title}
      extra={t(`bot:hints.${key}`, { defaultValue: s.description ?? "" }) || undefined}
      valuePropName={kind === "boolean" ? "checked" : "value"}
    >
      {control(t, key, s, title)}
    </Form.Item>
  );
}
