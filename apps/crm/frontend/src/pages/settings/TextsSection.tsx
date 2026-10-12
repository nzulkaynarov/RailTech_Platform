import {
  Button,
  Collapse,
  Drawer,
  Flex,
  Form,
  Grid,
  Input,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useState } from "react";

import { LocalizedFields, SchemaField } from "../../components/SchemaFields";
import { type JsonSchema, kindOf, resolve } from "../../domain/schemaForm";
import {
  emptyLanguages,
  fieldLabel,
  matchesText,
  oneLine,
  textGroups,
} from "../../domain/settingsLayout";
import { languageLabel } from "../../domain/labels";
import { t } from "../../i18n/ru";

type Props = {
  schema: JsonSchema;
  samples: Record<string, string>;
  saving: boolean;
  /** Невалидные поля из ответа сервера: строка помечается, панель открывается на первом. */
  invalid: string[][];
};
type Row = { key: string; label: string; when: string | undefined; invalid: boolean };
const LANGS = ["ru", "uz", "en"] as const;

/** Ячейка языка: текст в одну строку с подсказкой целиком; пустой перевод — тег «пусто». */
function LangCell({ field, lang }: { field: string; lang: string }) {
  const text = oneLine(Form.useWatch([field, lang], { preserve: true }));
  if (!text) return <Tag color="warning">{t.settingsUi.textEmpty}</Tag>;
  return (
    <Tooltip title={text} placement="topLeft">
      <Typography.Text ellipsis className="settings-text-cell">
        {text}
      </Typography.Text>
    </Tooltip>
  );
}

/** Телефон: колонок языков нет — пустые переводы отмечаются тегом под названием. */
function EmptyMark({ field }: { field: string }) {
  const empty = emptyLanguages(Form.useWatch([field], { preserve: true }));
  if (empty.length === 0) return null;
  return (
    <span>
      <Tag color="warning">
        {t.settingsUi.textEmpty}: {empty.map(languageLabel).join(", ")}
      </Tag>
    </span>
  );
}

function TextsTable({ rows, onEdit }: { rows: Row[]; onEdit: (key: string) => void }) {
  const phone = Grid.useBreakpoint().md === false;
  return (
    <Table<Row>
      size="small"
      rowKey="key"
      pagination={false}
      dataSource={rows}
      tableLayout="fixed"
      columns={[
        {
          title: t.settingsUi.textName,
          key: "name",
          render: (_, row) => (
            <Flex vertical>
              <span>
                <Typography.Text strong>{row.label}</Typography.Text>{" "}
                {row.invalid ? <Tag color="error">{t.settingsUi.textInvalid}</Tag> : null}
              </span>
              {row.when ? (
                <Typography.Text type="secondary" className="settings-text-when">
                  {row.when}
                </Typography.Text>
              ) : null}
              {phone ? <EmptyMark field={row.key} /> : null}
            </Flex>
          ),
        },
        ...LANGS.map((lang) => ({
          title: languageLabel(lang),
          key: lang,
          responsive: ["md" as const],
          render: (_: unknown, row: Row) => <LangCell field={row.key} lang={lang} />,
        })),
        {
          title: <span className="sr-only">{t.settingsUi.textActions}</span>,
          key: "edit",
          width: 110,
          render: (_, row) => (
            <Button
              type="link"
              aria-label={`${t.settingsUi.textEdit}: ${row.label}`}
              onClick={() => {
                onEdit(row.key);
              }}
            >
              {t.settingsUi.textEdit}
            </Button>
          ),
        },
      ]}
    />
  );
}

/**
 * «Тексты бота»: группы по смыслу (`Collapse`), в группе — таблица «название · ru · uz · en»,
 * правка — в боковой панели с тремя полями и предпросмотром. Сохранение — одно на раздел
 * (кнопка в шапке), тело PUT — все тексты, как раньше.
 */
export function TextsSection({ schema, samples, saving, invalid }: Props) {
  const form = Form.useFormInstance();
  const phone = Grid.useBreakpoint().sm === false;
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [open, setOpen] = useState<string[] | null>(null);
  const invalidKeys = new Set(invalid.map((path) => path[0]));
  const firstInvalid = invalid[0]?.[0];
  // Новый ответ сервера с ошибками — открыть панель на первом невалидном тексте
  // (подстройка состояния при рендере, без эффекта).
  const [seenInvalid, setSeenInvalid] = useState(invalid);
  if (seenInvalid !== invalid) {
    setSeenInvalid(invalid);
    if (firstInvalid) setEditing(firstInvalid);
  }
  const { schema: s } = resolve(schema, schema);
  const properties = s.properties ?? {};
  const isText = (key: string) =>
    kindOf(resolve(properties[key] ?? {}, schema).schema) === "localized";
  const groups = textGroups(Object.keys(properties))
    .map((g) => ({ ...g, fields: g.fields.filter((f) => !isText(f) || matchesText(f, query)) }))
    .filter((g) => g.fields.length > 0);
  const activeKey = query.trim()
    ? groups.map((g) => g.key)
    : (open ?? (groups[0] ? [groups[0].key] : []));
  const row = (key: string): Row => ({
    key,
    label: fieldLabel(key, properties[key] ?? {}),
    when: t.settings.botTexts[key]?.when,
    invalid: invalidKeys.has(key),
  });
  const editingLabel = editing ? row(editing).label : "";

  return (
    <>
      <Input.Search
        allowClear
        className="mb-16"
        placeholder={t.settingsUi.textSearch}
        aria-label={t.settingsUi.textSearch}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
        }}
      />
      {groups.length === 0 ? (
        <Typography.Text type="secondary">{t.settingsUi.textNotFound}</Typography.Text>
      ) : (
        <Collapse
          activeKey={activeKey}
          onChange={(keys) => {
            setOpen(Array.isArray(keys) ? keys : [keys]);
          }}
          items={groups.map((group) => ({
            key: group.key,
            label: `${t.settings.textGroups[group.key] ?? group.key} · ${String(group.fields.length)}`,
            children: (
              <>
                <TextsTable rows={group.fields.filter(isText).map(row)} onEdit={setEditing} />
                {group.fields
                  .filter((key) => !isText(key))
                  .map((key) => (
                    <SchemaField
                      key={key}
                      name={[key]}
                      schema={properties[key] ?? {}}
                      root={schema}
                      label={fieldLabel(key, properties[key] ?? {})}
                      samples={samples}
                    />
                  ))}
              </>
            ),
          }))}
        />
      )}
      <Drawer
        open={editing !== null}
        title={editingLabel}
        width={phone ? "100%" : 560}
        onClose={() => {
          setEditing(null);
        }}
        afterOpenChange={(visible) => {
          // Поля панели появились — показать на них ошибки сервера.
          if (!visible || !editing) return;
          form.setFields(
            invalid
              .filter((path) => path[0] === editing)
              .map((name) => ({ name, errors: [t.settingsUi.invalidField] })),
          );
        }}
        footer={
          <Flex gap="small" justify="end">
            <Button
              onClick={() => {
                setEditing(null);
              }}
            >
              {t.settingsUi.textClose}
            </Button>
            <Button type="primary" loading={saving} onClick={form.submit}>
              {t.common.save}
            </Button>
          </Flex>
        }
      >
        {editing ? (
          <>
            {row(editing).when ? (
              <Typography.Paragraph type="secondary">{row(editing).when}</Typography.Paragraph>
            ) : null}
            <LocalizedFields name={[editing]} label={editingLabel} samples={samples} />
          </>
        ) : null}
      </Drawer>
    </>
  );
}
