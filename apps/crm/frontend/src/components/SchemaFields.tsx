import {
  Badge,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Switch,
  Tabs,
  Typography,
} from "antd";

import { t } from "../i18n/ru";
import { bounds, type JsonSchema, kindOf, resolve } from "../domain/schemaForm";
import {
  emptyLanguages,
  fieldLabel,
  fillPlaceholders,
  hasPlaceholders,
  isShortField,
  widgetFor,
} from "../domain/settingsLayout";
import { languageLabel } from "../domain/labels";
import { SettingsWidget } from "./SettingsWidgets";

type Props = {
  name: (string | number)[];
  schema: JsonSchema;
  root: JsonSchema;
  label: string;
  /** Подстановки для предпросмотра текстов: `{company}`, `{hours}`… */
  samples: Record<string, string>;
};

function enumOptions(values: unknown[] | undefined) {
  return (values ?? []).map((v) => ({
    value: String(v),
    label: t.settings.options[String(v)] ?? String(v),
  }));
}

const lastKey = (name: (string | number)[]) => String(name[name.length - 1] ?? "");

function LanguageTab({ lang, empty }: { lang: string; empty: boolean }) {
  return empty ? (
    <Badge dot title={t.settings.emptyTranslation}>
      {languageLabel(lang)}
    </Badge>
  ) : (
    <>{languageLabel(lang)}</>
  );
}

function Preview({ name, samples }: { name: (string | number)[]; samples: Props["samples"] }) {
  const text = String(Form.useWatch(name, { preserve: true }) ?? "");
  if (!hasPlaceholders(text)) return null;
  return (
    <Typography.Paragraph type="secondary" className="settings-preview">
      {t.settings.preview}: {fillPlaceholders(text, samples)}
    </Typography.Paragraph>
  );
}

/** Текст на трёх языках: подпись, «когда отправляется», точка на вкладке без перевода. */
function Localized({ name, label: title, samples }: Omit<Props, "schema" | "root">) {
  const value: unknown = Form.useWatch(name, { preserve: true });
  const empty = emptyLanguages(value);
  const when = t.settings.botTexts[lastKey(name)]?.when;
  return (
    <Card size="small" title={title} className="settings-text">
      {when ? <Typography.Text type="secondary">{when}</Typography.Text> : null}
      <Tabs
        size="small"
        items={(["ru", "uz", "en"] as const).map((lang) => ({
          key: lang,
          label: <LanguageTab lang={lang} empty={empty.includes(lang)} />,
          children: (
            <>
              <Form.Item name={[...name, lang]} rules={[{ required: true, whitespace: true }]}>
                <Input.TextArea
                  aria-label={`${title} · ${languageLabel(lang)}`}
                  autoSize={{ minRows: 2, maxRows: 8 }}
                />
              </Form.Item>
              <Preview name={[...name, lang]} samples={samples} />
            </>
          ),
        }))}
      />
    </Card>
  );
}

/** Три поля ru/uz/en друг под другом с предпросмотром — редактор текста бота в панели. */
export function LocalizedFields({ name, label: title, samples }: Omit<Props, "schema" | "root">) {
  return (
    <>
      {(["ru", "uz", "en"] as const).map((lang) => (
        <div key={lang}>
          <Form.Item
            name={[...name, lang]}
            label={languageLabel(lang)}
            rules={[{ required: true, whitespace: true, message: t.settings.emptyTranslation }]}
          >
            <Input.TextArea
              aria-label={`${title} · ${languageLabel(lang)}`}
              autoSize={{ minRows: 3, maxRows: 10 }}
            />
          </Form.Item>
          <Preview name={[...name, lang]} samples={samples} />
        </div>
      ))}
    </>
  );
}

function control(key: string, s: JsonSchema) {
  const format = s.type === "array" ? s.items?.format : s.format;
  const widget = widgetFor(key, format ? { format } : {});
  if (widget) return <SettingsWidget widget={widget} />;
  switch (kindOf(s)) {
    case "boolean":
      return <Switch />;
    case "integer":
    case "number":
      return (
        <InputNumber
          className="settings-number"
          step={kindOf(s) === "integer" ? 1 : 0.05}
          suffix={t.settings.units[key]}
          {...bounds(s)}
        />
      );
    case "tags":
    case "number-tags":
      return <Select mode="tags" tokenSeparators={[","]} open={false} suffixIcon={null} />;
    case "enum":
      return <Select options={enumOptions(s.enum)} />;
    case "multi-enum":
      return <Select mode="multiple" options={enumOptions(s.items?.enum)} />;
    default:
      return s.description && s.description.length > 80 ? <Input.TextArea autoSize /> : <Input />;
  }
}

/** Поле формы настроек по JSON Schema pydantic (рекурсивно для вложенных объектов). */
export function SchemaField({ name, schema, root, label: title, samples }: Props) {
  const { schema: s } = resolve(schema, root);
  const kind = kindOf(s);
  if (kind === "localized") return <Localized name={name} label={title} samples={samples} />;
  if (kind === "object") {
    // Короткие поля (числа, переключатели, выбор) — по два в ряд на широком экране.
    return (
      <Row gutter={16}>
        {Object.entries(s.properties ?? {}).map(([key, child]) => (
          <Col key={key} xs={24} lg={isShortField(key, resolve(child, root).schema) ? 12 : 24}>
            <SchemaField
              name={[...name, key]}
              schema={child}
              root={root}
              label={fieldLabel(key, child)}
              samples={samples}
            />
          </Col>
        ))}
      </Row>
    );
  }
  const key = lastKey(name);
  return (
    <Form.Item
      name={name}
      label={title}
      extra={t.settings.hints[key] ?? s.description}
      valuePropName={kind === "boolean" ? "checked" : "value"}
    >
      {control(key, s)}
    </Form.Item>
  );
}
