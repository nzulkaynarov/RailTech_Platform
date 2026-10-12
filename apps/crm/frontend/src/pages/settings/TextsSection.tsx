import { Collapse } from "antd";

import { SchemaField } from "../../components/SchemaFields";
import { type JsonSchema, resolve } from "../../domain/schemaForm";
import { fieldLabel, textGroups } from "../../domain/settingsLayout";
import { t } from "../../i18n/ru";

type Props = { schema: JsonSchema; samples: Record<string, string> };

/** «Тексты бота»: сворачиваемые группы по смыслу вместо одной страницы на 8000 px. */
export function TextsSection({ schema, samples }: Props) {
  const { schema: s } = resolve(schema, schema);
  const properties = s.properties ?? {};
  const groups = textGroups(Object.keys(properties));
  return (
    <Collapse
      defaultActiveKey={groups[0] ? [groups[0].key] : []}
      items={groups.map((group) => ({
        key: group.key,
        label: `${t.settings.textGroups[group.key] ?? group.key} · ${String(group.fields.length)}`,
        children: group.fields.map((key) => {
          const child = properties[key] ?? {};
          return (
            <SchemaField
              key={key}
              name={[key]}
              schema={child}
              root={schema}
              label={fieldLabel(key, child)}
              samples={samples}
            />
          );
        }),
      }))}
    />
  );
}
