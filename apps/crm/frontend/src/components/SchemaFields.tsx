import { Card, Form, Input, InputNumber, Select, Switch, Tabs, Typography } from "antd";

import { t } from "../i18n/ru";
import { bounds, type JsonSchema, kindOf, resolve } from "./schemaForm";
import { languageLabel } from "../domain/labels";

type Props = {
  name: (string | number)[];
  schema: JsonSchema;
  root: JsonSchema;
  label: string;
  company: string;
};

function enumOptions(values: unknown[] | undefined) {
  return (values ?? []).map((v) => ({
    value: String(v),
    label: t.settings.options[String(v)] ?? String(v),
  }));
}

function label(key: string, schema: JsonSchema): string {
  return t.settings.fields[key] ?? schema.title ?? key;
}

function Localized({ name, label: title, company }: Omit<Props, "schema" | "root">) {
  return (
    <Card size="small" title={title} style={{ marginBottom: 12 }}>
      <Tabs
        size="small"
        items={(["ru", "uz", "en"] as const).map((lang) => ({
          key: lang,
          label: languageLabel(lang),
          children: (
            <>
              <Form.Item name={[...name, lang]} rules={[{ required: true }]}>
                <Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} />
              </Form.Item>
              <Form.Item noStyle shouldUpdate>
                {({ getFieldValue }) => (
                  <Typography.Paragraph type="secondary" style={{ whiteSpace: "pre-wrap" }}>
                    {t.settings.preview}:{" "}
                    {String(getFieldValue([...name, lang]) ?? "")
                      .replaceAll("{company}", company)
                      .replaceAll("{hours}", t.settings.hoursSample)}
                  </Typography.Paragraph>
                )}
              </Form.Item>
            </>
          ),
        }))}
      />
    </Card>
  );
}

/** Поле формы настроек по JSON Schema pydantic (рекурсивно для вложенных объектов). */
export function SchemaField({ name, schema, root, label: title, company }: Props) {
  const { schema: s } = resolve(schema, root);
  const kind = kindOf(s);
  if (kind === "localized") return <Localized name={name} label={title} company={company} />;
  if (kind === "object") {
    return (
      <>
        {Object.entries(s.properties ?? {}).map(([key, child]) => (
          <SchemaField
            key={key}
            name={[...name, key]}
            schema={child}
            root={root}
            label={label(key, child)}
            company={company}
          />
        ))}
      </>
    );
  }
  const control = (() => {
    switch (kind) {
      case "boolean":
        return <Switch />;
      case "integer":
      case "number":
        return (
          <InputNumber style={{ width: 200 }} step={kind === "integer" ? 1 : 0.05} {...bounds(s)} />
        );
      case "tags":
      case "number-tags":
        return <Select mode="tags" tokenSeparators={[","]} />;
      case "enum":
        return <Select options={enumOptions(s.enum)} />;
      case "multi-enum":
        return <Select mode="multiple" options={enumOptions(s.items?.enum)} />;
      default:
        return s.description && s.description.length > 80 ? <Input.TextArea autoSize /> : <Input />;
    }
  })();
  return (
    <Form.Item name={name} label={title} valuePropName={kind === "boolean" ? "checked" : "value"}>
      {control}
    </Form.Item>
  );
}
