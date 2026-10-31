import { Button, Collapse, Form, Input, Typography } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import { Consequence } from "../../../shared/ui/Consequence";
import { useViewport } from "../../../app/shell/useViewport";
import { ScrollRegion } from "../../../shared/ui/FormParts";
import { withParams } from "./refresh";
import { fieldLabel } from "./fieldLabel";
import { LocalizedFields, SchemaField } from "./SchemaField";
import { type JsonSchema, kindOf, resolve } from "./schemaForm";
import { emptyLanguages, matchesText, oneLine, textGroups } from "./sections";
import { StatusTag } from "../../../shared/ui/StatusTag";

interface Props {
  schema: JsonSchema;
  samples: Record<string, string>;
  saving: boolean;
  /** Невалидные поля из ответа сервера: строка помечается, панель открывается на первом. */
  invalid: string[][];
  editable: boolean;
}

const LANGS = ["ru", "uz", "en"] as const;

/** Ячейка языка: текст в одну строку с подсказкой целиком; пустой перевод — тег «пусто». */
function LangCell({ field, lang }: { field: string; lang: string }) {
  const { t } = useTranslation("bot");
  const text = oneLine(Form.useWatch([field, lang], { preserve: true }));
  if (!text) return <StatusTag tone="gold">{t("texts.empty")}</StatusTag>;
  return (
    <span className="pf-bot-text-cell" title={text}>
      {text}
    </span>
  );
}

/** Узкий экран: колонок языков нет — пустые переводы отмечаются тегом под названием. */
function EmptyMark({ field }: { field: string }) {
  const { t } = useTranslation(["bot", "kb"]);
  const empty = emptyLanguages(Form.useWatch([field], { preserve: true }));
  if (empty.length === 0) return null;
  return (
    <span>
      <StatusTag tone="gold">
        {t("bot:texts.empty")}: {empty.map((l) => t(`kb:languages.${l}`)).join(", ")}
      </StatusTag>
    </span>
  );
}

interface Row {
  key: string;
  label: string;
  when: string;
  invalid: boolean;
}

function TextsTable({
  rows,
  onEdit,
  editable,
}: {
  rows: Row[];
  onEdit: (key: string) => void;
  editable: boolean;
}) {
  const { t } = useTranslation(["bot", "kb"]);
  const { mobile } = useViewport();
  return (
    <ScrollRegion label={t("bot:texts.tableScroll")}>
      <table className={mobile ? "pf-bot-table" : "pf-bot-table pf-bot-table--texts"}>
        <caption className="pf-sr-only">{t("bot:texts.caption")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("bot:texts.name")}</th>
            {mobile
              ? null
              : LANGS.map((lang) => (
                  <th scope="col" key={lang}>
                    {t(`kb:languages.${lang}`)}
                  </th>
                ))}
            <th scope="col">
              <span className="pf-sr-only">{t("bot:texts.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>
                <strong>{row.label}</strong>{" "}
                {row.invalid ? <StatusTag tone="red">{t("bot:texts.invalid")}</StatusTag> : null}
                {row.when ? <div className="pf-hint">{row.when}</div> : null}
                {mobile ? <EmptyMark field={row.key} /> : null}
              </td>
              {mobile
                ? null
                : LANGS.map((lang) => (
                    <td key={lang}>
                      <LangCell field={row.key} lang={lang} />
                    </td>
                  ))}
              <td>
                <Button
                  type="link"
                  aria-label={`${t(editable ? "bot:texts.edit" : "bot:texts.view")}: ${row.label}`}
                  onClick={() => {
                    onEdit(row.key);
                  }}
                >
                  {t(editable ? "bot:texts.edit" : "bot:texts.view")}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/**
 * «Тексты бота»: группы по смыслу, в группе — таблица «название · ru · uz · en», правка — в боковом окне с тремя полями и
 * предпросмотром (`?text=<ключ>`). Сохранение одно на раздел (кнопка в шапке формы), тело PUT — все тексты.
 */
export function TextsSection({ schema, samples, saving, invalid, editable }: Props) {
  const { t, i18n } = useTranslation(["bot", "kb"]);
  const form = Form.useFormInstance();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string[] | null>(null);
  const invalidKeys = new Set(invalid.map((path) => path[0]));
  const requested = params.get("text");
  const { schema: s } = resolve(schema, schema);
  const properties = s.properties ?? {};
  const editing = requested !== null && requested in properties ? requested : null;

  const isText = (key: string) =>
    kindOf(resolve(properties[key] ?? {}, schema).schema) === "localized";
  // Подпись и «когда» — из словаря; нового текста CRM в словаре ещё нет — подпись берётся из схемы CRM.
  const label = (key: string) =>
    i18n.exists(`bot:texts.items.${key}.label`)
      ? t(`bot:texts.items.${key}.label`)
      : fieldLabel(t, key, properties[key] ?? {});
  const when = (key: string) =>
    i18n.exists(`bot:texts.items.${key}.when`) ? t(`bot:texts.items.${key}.when`) : "";
  const groups = textGroups(Object.keys(properties))
    .map((g) => ({
      ...g,
      fields: g.fields.filter((f) => matchesText(f, query, label(f), when(f))),
    }))
    .filter((g) => g.fields.length > 0);
  const activeKey = query.trim()
    ? groups.map((g) => g.key)
    : (open ?? (groups[0] ? [groups[0].key] : []));
  const row = (key: string): Row => ({
    key,
    label: label(key),
    when: when(key),
    invalid: invalidKeys.has(key),
  });
  const edit = (key: string | null) => {
    void navigate(
      { search: withParams(params, { text: key, panel: key ? "open" : null }) },
      { replace: true },
    );
  };

  // Ответ сервера с ошибками: панель открывается на первом невалидном тексте, его поля подсвечиваются.
  const first = invalid[0]?.[0] ?? null;
  useEffect(() => {
    if (first !== null && first in properties && first !== requested) edit(first);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- только на новый ответ сервера
  }, [invalid]);
  useEffect(() => {
    if (editing === null) return;
    form.setFields(
      invalid
        .filter((path) => path[0] === editing)
        .map((name) => ({ name, errors: [t("bot:form.invalidField")] })),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- поля панели появились или пришёл новый ответ сервера
  }, [editing, invalid]);

  return (
    <>
      <Input.Search
        allowClear
        className="pf-bot-search"
        placeholder={t("bot:texts.search")}
        aria-label={t("bot:texts.search")}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      {groups.length === 0 ? (
        <Typography.Text type="secondary">{t("bot:texts.notFound")}</Typography.Text>
      ) : (
        <Collapse
          activeKey={activeKey}
          onChange={(keys) => {
            setOpen(Array.isArray(keys) ? keys : [keys]);
          }}
          items={groups.map((group) => ({
            key: group.key,
            label: `${t(`bot:texts.groups.${group.key}`, { defaultValue: group.key })} · ${String(group.fields.length)}`,
            children: (
              <>
                <TextsTable
                  rows={group.fields.filter(isText).map(row)}
                  onEdit={edit}
                  editable={editable}
                />
                {group.fields
                  .filter((key) => !isText(key))
                  .map((key) => (
                    <SchemaField
                      key={key}
                      name={[key]}
                      schema={properties[key] ?? {}}
                      root={schema}
                      label={fieldLabel(t, key, properties[key] ?? {})}
                      samples={samples}
                    />
                  ))}
              </>
            ),
          }))}
        />
      )}
      {editing ? (
        <PanelPortal tab="card">
          <div className="pf-fp-stack">
            <h3 className="pf-fp-title">{label(editing)}</h3>
            {when(editing) ? <p className="pf-fp-sub">{when(editing)}</p> : null}
            <LocalizedFields name={[editing]} label={label(editing)} samples={samples} />
            {editable ? (
              <>
                <Consequence
                  items={[t("bot:texts.step1"), t("bot:texts.step2"), t("bot:texts.step3")]}
                />
                <div className="pf-fp-row">
                  <Button type="primary" loading={saving} onClick={form.submit}>
                    {t("bot:texts.save")}
                  </Button>
                  <Button
                    onClick={() => {
                      edit(null);
                    }}
                  >
                    {t("bot:texts.close")}
                  </Button>
                </div>
              </>
            ) : null}
          </div>
        </PanelPortal>
      ) : null}
    </>
  );
}
