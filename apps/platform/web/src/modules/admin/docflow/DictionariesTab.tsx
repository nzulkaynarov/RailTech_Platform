import { ArrowDownOutlined, ArrowUpOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Skeleton,
} from "antd";
import type { TFunction } from "i18next";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type {
  Dictionary,
  DictionaryAttr,
  DictionaryAttrValues,
  DictionaryItem,
} from "../../../shared/api/generated/model";
import {
  getListDictionariesQueryKey,
  getListDictionaryItemsQueryKey,
  useCreateDictionaryItem,
  useDeleteDictionaryItem,
  useListDictionaries,
  useListDictionaryItems,
  useReorderDictionaryItems,
  useSyncDictionary,
  useUpdateDictionaryItem,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { localName } from "../../eds/dictionaries";
import { ConfirmModal, ListTable, TabHeader } from "../company/common";
import { DictionaryFile } from "./DictionaryFile";
import { dictionaryErrorText } from "./errors";

/**
 * Настройки · Документооборот · Справочники (EDS-REG; исследование «Настройки» §4.3): справочник сверху переключателем,
 * значения таблицей — название, поля вида (из каталога), статус, порядок стрелками; добавить, изменить, скрыть или вернуть,
 * удалить неиспользованное. Использованное значение не удаляется, его скрывают: в формах его нет, у старых писем остаётся.
 */
export function DictionariesTab({ readOnly, kind: fixed }: { readOnly: boolean; kind?: string }) {
  const { t, i18n } = useTranslation("letters");
  const catalog = useListDictionaries({ query: { staleTime: 5 * 60_000 } });
  // Каталог BFF — справочники всех доменов; на этом экране все они — документооборота (`area = documents`).
  const dictionaries = catalog.data?.items ?? [];
  const [chosen, setKind] = useState<string | null>(null);
  const kind = fixed ?? chosen;
  const current = dictionaries.find((d) => d.kind === kind) ?? dictionaries[0];
  // На странице «Процессы · Справочники» (SET-IA) справочник выбран слева: заголовок — его название, переключателя нет.
  const title =
    fixed && current ? localName(current.name, i18n.language) : t("settings.dict.title");

  return (
    <div className="pf-co-body">
      <TabHeader title={title} hint={t("settings.dict.hint")} />
      {catalog.isPending ? <Skeleton active paragraph={{ rows: 6 }} title={false} /> : null}
      {catalog.isError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={t("settings.dict.errors.load")}
          action={
            <Button size="small" onClick={() => void catalog.refetch()}>
              {t("settings.dict.retry")}
            </Button>
          }
        />
      ) : null}
      {current ? (
        <>
          {fixed ? null : (
            <div className="pf-docflow-kinds">
              <Segmented<string>
                aria-label={t("settings.dict.kindLabel")}
                value={current.kind}
                onChange={setKind}
                options={dictionaries.map((d) => ({
                  value: d.kind,
                  label: localName(d.name, i18n.language),
                }))}
              />
            </div>
          )}
          <DictionaryTable key={current.kind} dictionary={current} readOnly={readOnly} />
        </>
      ) : null}
    </div>
  );
}

function attrText(
  t: TFunction<"letters">,
  attr: DictionaryAttr,
  value: unknown,
  language: string,
): string {
  if (attr.type === "boolean")
    return value === true ? t("settings.dict.yes") : t("settings.dict.no");
  if (attr.type === "choice") {
    const option = attr.options?.find((o) => o.value === value);
    if (option) return localName(option.name, language);
    return typeof value === "string" ? value : t("settings.dict.no");
  }
  if (attr.type === "text" || attr.type === "decimal") {
    return typeof value === "string" && value !== "" ? value : "—";
  }
  return typeof value === "number" ? String(value) : t("settings.dict.generalRule");
}

const PAGE_SIZE = 20;

function DictionaryTable({ dictionary, readOnly }: { dictionary: Dictionary; readOnly: boolean }) {
  const { t, i18n } = useTranslation("letters");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const params = { include_hidden: true };
  const query = useListDictionaryItems(dictionary.kind, params);
  const [editing, setEditing] = useState<DictionaryItem | "new" | null>(null);
  const [removing, setRemoving] = useState<DictionaryItem | null>(null);
  const [error, setError] = useState<unknown>(null);
  const kind = dictionary.kind;
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: getListDictionaryItemsQueryKey(kind) });
  };
  const onError = (e: unknown) => {
    setError(e);
  };
  const toggle = useUpdateDictionaryItem({
    mutation: {
      onSuccess: (item) => {
        refresh();
        setError(null);
        void message.success(
          t(item.active ? "settings.dict.shownToast" : "settings.dict.hiddenToast"),
        );
      },
      onError,
    },
  });
  const reorder = useReorderDictionaryItems({ mutation: { onSuccess: refresh, onError } });
  const remove = useDeleteDictionaryItem({
    mutation: {
      onSuccess: () => {
        refresh();
        setRemoving(null);
        void message.success(t("settings.dict.deleted"));
      },
    },
  });
  // Список с открытым источником (валюты — ЦБ): «Обновить» — только администратор (решение 2026-11-11).
  const { me } = useAuth();
  const { date } = useFormat();
  const source = dictionary.source ?? null;
  const sync = useSyncDictionary({
    mutation: {
      onSuccess: () => {
        setError(null);
        void message.success(t("settings.dict.source.queued"));
        void queryClient.invalidateQueries({ queryKey: getListDictionariesQueryKey() });
      },
      onError,
    },
  });
  const items = query.data?.items ?? [];
  const name = (item: DictionaryItem) => localName(item.name, i18n.language);
  // Длинные списки (250 стран): поиск по коду и названиям на трёх языках и страницы по 20.
  const [search, setSearch] = useState("");
  const needle = search.trim().toLowerCase();
  const shown = needle
    ? items.filter((item) =>
        [item.code, item.name.ru, item.name.uz, item.name.en].some((v) =>
          v.toLowerCase().includes(needle),
        ),
      )
    : items;
  const move = (index: number, step: -1 | 1) => {
    const codes = items.map((item) => item.code);
    const [code] = codes.splice(index, 1);
    if (code === undefined) return;
    codes.splice(index + step, 0, code);
    reorder.mutate({ kind, data: { codes } });
  };
  const add = (
    <Button
      type="primary"
      disabled={readOnly}
      onClick={() => {
        setEditing("new");
      }}
    >
      {t("settings.dict.add")}
    </Button>
  );

  return (
    <>
      <div className="pf-co-actions">
        {source ? (
          <span className="pf-co-hint">
            {t("settings.dict.source.line", {
              name: localName(source.name, i18n.language),
              when: source.synced_at
                ? date(source.synced_at, "datetime")
                : t("settings.dict.source.never"),
            })}
          </span>
        ) : null}
        {source && canEdit(me, "admin") ? (
          <Button
            loading={sync.isPending}
            onClick={() => {
              sync.mutate({ kind });
            }}
          >
            {t("settings.dict.source.refresh")}
          </Button>
        ) : null}
        {add}
        <DictionaryFile dictionary={dictionary} readOnly={readOnly} />
      </div>
      {error ? (
        <Alert type="error" showIcon role="alert" message={dictionaryErrorText(t, error)} />
      ) : null}
      {query.isError ? (
        <Alert type="error" showIcon role="alert" message={t("settings.dict.errors.load")} />
      ) : null}
      {items.length > PAGE_SIZE ? (
        <Input.Search
          allowClear
          className="pf-co-search"
          aria-label={t("settings.dict.search")}
          placeholder={t("settings.dict.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
        />
      ) : null}
      <ListTable<DictionaryItem>
        tableId="admin.docflow.dictionary"
        pageSize={PAGE_SIZE}
        label={localName(dictionary.name, i18n.language)}
        data={shown}
        loading={query.isPending}
        rowKey={(row) => row.code}
        empty={{
          title: needle ? t("settings.dict.noMatch") : t("settings.dict.empty.title"),
          text: needle ? "" : t("settings.dict.empty.text"),
          // Пока список грузится, antd показывает пустое состояние под спиннером: без второй кнопки «Добавить».
          action: query.isPending ? undefined : add,
        }}
        columns={[
          ...(dictionary.codes === "given"
            ? [
                {
                  id: "code",
                  header: t("settings.dict.code"),
                  width: null,
                  cell: (row: DictionaryItem) => row.code,
                },
              ]
            : []),
          {
            id: "name",
            header: t("settings.dict.name"),
            width: null,
            cell: (row) => <b>{name(row)}</b>,
          },
          // «Значок» виден в самой метке типа; в таблице он только отнимал бы ширину.
          ...dictionary.attrs
            .filter((attr) => attr.key !== "icon")
            .map((attr) => ({
              id: attr.key,
              header: localName(attr.name, i18n.language),
              width: null,
              cell: (row: DictionaryItem) => attrText(t, attr, row.attrs[attr.key], i18n.language),
            })),
          ...(source
            ? [
                {
                  id: "source",
                  header: t("settings.dict.source.column"),
                  width: null,
                  cell: (row: DictionaryItem) =>
                    row.source?.missing ? (
                      <StatusTag kind="origin" status="missing">
                        {t("settings.dict.source.missing")}
                      </StatusTag>
                    ) : row.source ? (
                      [
                        localName(row.source.name, i18n.language),
                        row.source.synced_at ? date(row.source.synced_at) : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")
                    ) : (
                      t("settings.dict.source.manual")
                    ),
                },
              ]
            : []),
          {
            id: "active",
            header: t("settings.dict.status"),
            width: null,
            cell: (row) => (
              <StatusTag kind="activity" status={row.active ? "active" : "inactive"}>
                {row.active ? t("settings.dict.active") : t("settings.dict.hidden")}
              </StatusTag>
            ),
          },
          {
            id: "order",
            header: t("settings.dict.order"),
            width: null,
            cell: (row) => {
              // Номер в полном списке, а не на странице или в отборе поиска
              const index = items.indexOf(row);
              return (
                <span className="pf-co-actions">
                  <Button
                    size="small"
                    icon={<ArrowUpOutlined />}
                    aria-label={t("settings.dict.up", { name: name(row) })}
                    disabled={readOnly || index === 0 || reorder.isPending}
                    onClick={() => {
                      move(index, -1);
                    }}
                  />
                  <Button
                    size="small"
                    icon={<ArrowDownOutlined />}
                    aria-label={t("settings.dict.down", { name: name(row) })}
                    disabled={readOnly || index === items.length - 1 || reorder.isPending}
                    onClick={() => {
                      move(index, 1);
                    }}
                  />
                </span>
              );
            },
          },
          {
            id: "actions",
            header: t("settings.dict.actions"),
            width: 160,
            cell: (row) => (
              <span className="pf-co-actions">
                <Button
                  type="link"
                  size="small"
                  disabled={readOnly}
                  aria-label={t("settings.dict.editNamed", { name: name(row) })}
                  onClick={() => {
                    setEditing(row);
                  }}
                >
                  {t("settings.dict.edit")}
                </Button>
                {dictionary.closed ? null : (
                  <Button
                    type="link"
                    size="small"
                    disabled={readOnly}
                    loading={toggle.isPending && toggle.variables.code === row.code}
                    aria-label={t(
                      row.active ? "settings.dict.hideNamed" : "settings.dict.showNamed",
                      {
                        name: name(row),
                      },
                    )}
                    onClick={() => {
                      toggle.mutate({ kind, code: row.code, data: { active: !row.active } });
                    }}
                  >
                    {t(row.active ? "settings.dict.hide" : "settings.dict.show")}
                  </Button>
                )}
                {dictionary.closed || row.used === true ? null : (
                  <Button
                    type="link"
                    size="small"
                    danger
                    disabled={readOnly}
                    aria-label={t("settings.dict.deleteNamed", { name: name(row) })}
                    onClick={() => {
                      remove.reset();
                      setRemoving(row);
                    }}
                  >
                    {t("settings.dict.delete")}
                  </Button>
                )}
              </span>
            ),
          },
        ]}
      />
      {editing !== null ? (
        <ItemModal
          dictionary={dictionary}
          item={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
          onSaved={() => {
            refresh();
            setEditing(null);
            setError(null);
            void message.success(t("settings.dict.saved"));
          }}
        />
      ) : null}
      <ConfirmModal
        open={removing !== null}
        title={t("settings.dict.deleteTitle", { name: removing ? name(removing) : "" })}
        okLabel={t("settings.dict.delete")}
        danger
        loading={remove.isPending}
        onOk={() => {
          if (removing) remove.mutate({ kind, code: removing.code });
        }}
        onCancel={() => {
          setRemoving(null);
        }}
      >
        {remove.isError ? (
          <Alert
            type="error"
            showIcon
            role="alert"
            message={dictionaryErrorText(t, remove.error)}
          />
        ) : null}
      </ConfirmModal>
    </>
  );
}

/** Значение поля по умолчанию: флаг выключен, число пусто, выбор — без значения, кроме цвета и значка (нейтральные). */
function initialAttr(attr: DictionaryAttr): boolean | null | string {
  if (attr.type === "boolean") return false;
  if (attr.type === "text") return "";
  if (attr.type === "choice") {
    const neutral = attr.key === "color" ? "default" : attr.key === "icon" ? "mail" : null;
    return neutral && attr.options?.some((o) => o.value === neutral) ? neutral : null;
  }
  return null;
}

interface Values {
  code: string;
  ru: string;
  uz: string;
  en: string;
  attrs: DictionaryAttrValues;
}

/** Добавить или изменить значение: названия на трёх языках и поля вида по описанию каталога. */
function ItemModal({
  dictionary,
  item,
  onClose,
  onSaved,
}: {
  dictionary: Dictionary;
  item: DictionaryItem | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t, i18n } = useTranslation("letters");
  const formId = useId();
  const [form] = Form.useForm<Values>();
  const create = useCreateDictionaryItem({ mutation: { onSuccess: onSaved } });
  const update = useUpdateDictionaryItem({ mutation: { onSuccess: onSaved } });
  const mutation = item ? update : create;
  const given = dictionary.codes === "given";
  const initial: Values = {
    code: item?.code ?? "",
    ru: item?.name.ru ?? "",
    uz: item?.name.uz ?? "",
    en: item?.name.en ?? "",
    attrs: Object.fromEntries(
      dictionary.attrs.map((a) => [a.key, item?.attrs[a.key] ?? initialAttr(a)]),
    ),
  };
  const submit = (values: Values) => {
    const name = { ru: values.ru.trim(), uz: values.uz.trim(), en: values.en.trim() };
    const attrs = Object.fromEntries(
      dictionary.attrs.map((a) => [a.key, values.attrs[a.key] ?? initialAttr(a)]),
    );
    if (item) update.mutate({ kind: dictionary.kind, code: item.code, data: { name, attrs } });
    else
      create.mutate({
        kind: dictionary.kind,
        data: { name, attrs, ...(given ? { code: values.code.trim() } : {}) },
      });
  };

  return (
    <Modal
      open
      title={item ? t("settings.dict.editTitle") : t("settings.dict.addTitle")}
      onCancel={onClose}
      destroyOnHidden
      maskClosable={false}
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("settings.dict.cancel")}
        </Button>,
        <Button
          key="submit"
          type="primary"
          htmlType="submit"
          form={formId}
          loading={mutation.isPending}
        >
          {t("settings.dict.save")}
        </Button>,
      ]}
    >
      {mutation.isError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={dictionaryErrorText(t, mutation.error)}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      <Form<Values>
        id={formId}
        form={form}
        layout="vertical"
        initialValues={initial}
        onFinish={submit}
      >
        {given && !item ? (
          <Form.Item
            name="code"
            label={t("settings.dict.code")}
            extra={t("settings.dict.codeHint")}
            rules={[{ required: true, whitespace: true, message: t("settings.dict.required") }]}
          >
            <Input maxLength={50} autoComplete="off" />
          </Form.Item>
        ) : null}
        <Form.Item
          name="ru"
          label={t("settings.dict.nameRu")}
          rules={[{ required: true, whitespace: true, message: t("settings.dict.required") }]}
        >
          <Input maxLength={120} autoComplete="off" />
        </Form.Item>
        <Form.Item name="uz" label={t("settings.dict.nameUz")} extra={t("settings.dict.nameHint")}>
          <Input maxLength={120} autoComplete="off" />
        </Form.Item>
        <Form.Item name="en" label={t("settings.dict.nameEn")} extra={t("settings.dict.nameHint")}>
          <Input maxLength={120} autoComplete="off" />
        </Form.Item>
        {dictionary.attrs.map((attr) =>
          attr.type === "choice" ? (
            <Form.Item
              key={attr.key}
              name={["attrs", attr.key]}
              label={localName(attr.name, i18n.language)}
              // Не `required: true`: antd кладёт `aria-required` на корневой div списка, а он не поле (axe).
              rules={
                attr.required === false
                  ? []
                  : [
                      {
                        validator: (_rule, value: unknown) =>
                          value
                            ? Promise.resolve()
                            : Promise.reject(new Error(t("settings.dict.chooseRequired"))),
                      },
                    ]
              }
            >
              <Select
                allowClear={attr.required === false}
                placeholder={t("settings.dict.choose")}
                options={(attr.options ?? []).map((o) => ({
                  value: o.value,
                  label: localName(o.name, i18n.language),
                }))}
              />
            </Form.Item>
          ) : attr.type === "boolean" ? (
            <Form.Item key={attr.key} name={["attrs", attr.key]} valuePropName="checked">
              <Checkbox>{localName(attr.name, i18n.language)}</Checkbox>
            </Form.Item>
          ) : attr.type === "text" ? (
            <Form.Item
              key={attr.key}
              name={["attrs", attr.key]}
              label={localName(attr.name, i18n.language)}
            >
              <Input autoComplete="off" />
            </Form.Item>
          ) : attr.type === "decimal" ? (
            <Form.Item
              key={attr.key}
              name={["attrs", attr.key]}
              label={localName(attr.name, i18n.language)}
            >
              <InputNumber stringMode min="0" step="0.01" style={{ width: "100%" }} />
            </Form.Item>
          ) : (
            <Form.Item
              key={attr.key}
              name={["attrs", attr.key]}
              label={localName(attr.name, i18n.language)}
              extra={attr.key === "due_days" ? t("settings.dict.dueHint") : undefined}
            >
              <InputNumber
                min={attr.minimum ?? undefined}
                max={attr.maximum ?? undefined}
                precision={0}
                style={{ width: "100%" }}
              />
            </Form.Item>
          ),
        )}
      </Form>
    </Modal>
  );
}
