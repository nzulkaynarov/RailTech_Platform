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

import type {
  Dictionary,
  DictionaryAttr,
  DictionaryAttrValues,
  DictionaryItem,
} from "../../../shared/api/generated/model";
import {
  getListDictionaryItemsQueryKey,
  useCreateDictionaryItem,
  useDeleteDictionaryItem,
  useListDictionaries,
  useListDictionaryItems,
  useReorderDictionaryItems,
  useUpdateDictionaryItem,
} from "../../../shared/api/generated/platform-bff";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { localName } from "../../eds/dictionaries";
import { ConfirmModal, ListTable, TabHeader } from "../company/common";
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
  return typeof value === "number" ? String(value) : t("settings.dict.generalRule");
}

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
  const items = query.data?.items ?? [];
  const name = (item: DictionaryItem) => localName(item.name, i18n.language);
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
      <div className="pf-co-actions">{add}</div>
      {error ? (
        <Alert type="error" showIcon role="alert" message={dictionaryErrorText(t, error)} />
      ) : null}
      {query.isError ? (
        <Alert type="error" showIcon role="alert" message={t("settings.dict.errors.load")} />
      ) : null}
      <ListTable<DictionaryItem>
        wrap
        label={localName(dictionary.name, i18n.language)}
        data={items}
        loading={query.isPending}
        rowKey={(row) => row.code}
        empty={{
          title: t("settings.dict.empty.title"),
          text: t("settings.dict.empty.text"),
          // Пока список грузится, antd показывает пустое состояние под спиннером: без второй кнопки «Добавить».
          action: query.isPending ? undefined : add,
        }}
        columns={[
          {
            title: t("settings.dict.name"),
            key: "name",
            render: (_: unknown, row) => <b>{name(row)}</b>,
          },
          // «Значок» виден в самой метке типа; в таблице он только отнимал бы ширину.
          ...dictionary.attrs
            .filter((attr) => attr.key !== "icon")
            .map((attr) => ({
              title: localName(attr.name, i18n.language),
              key: attr.key,
              render: (_: unknown, row: DictionaryItem) =>
                attrText(t, attr, row.attrs[attr.key], i18n.language),
            })),
          {
            title: t("settings.dict.status"),
            key: "active",
            render: (_: unknown, row) => (
              <StatusTag kind="activity" status={row.active ? "active" : "inactive"}>
                {row.active ? t("settings.dict.active") : t("settings.dict.hidden")}
              </StatusTag>
            ),
          },
          {
            title: t("settings.dict.order"),
            key: "order",
            render: (_: unknown, row, index) => (
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
            ),
          },
          {
            title: t("settings.dict.actions"),
            key: "actions",
            render: (_: unknown, row) => (
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
                {dictionary.closed || row.used !== false ? null : (
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
        items={[t("settings.dict.consequence")]}
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
  if (attr.type === "choice") {
    const neutral = attr.key === "color" ? "default" : attr.key === "icon" ? "mail" : null;
    return neutral && attr.options?.some((o) => o.value === neutral) ? neutral : null;
  }
  return null;
}

interface Values {
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
  const initial: Values = {
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
    else create.mutate({ kind: dictionary.kind, data: { name, attrs } });
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
