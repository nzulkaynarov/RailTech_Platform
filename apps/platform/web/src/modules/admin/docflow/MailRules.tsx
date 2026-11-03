import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Input, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { MailSenderRule } from "../../../shared/api/generated/model";
import {
  getListMailSenderRulesQueryKey,
  useCreateMailSenderRule,
  useDeleteMailSenderRule,
  useListDictionaryItems,
  useListMailSenderRules,
} from "../../../shared/api/generated/platform-bff";
import { localName } from "../../eds/dictionaries";
import { ListTable, TabHeader } from "../company/common";

function ruleError(t: (key: string) => string, error: unknown): string {
  const base = "settings.dict.rules.errors.";
  const reason = error instanceof ApiError ? error.details["reason"] : undefined;
  return reason === "mail_rule_exists" || reason === "mail_type_inactive"
    ? t(`${base}${reason}`)
    : t(`${base}DEFAULT`);
}

/**
 * Настройки · Процессы · Справочники · Типы входящих писем · «Правила отправителей» (MAIL-TYPES): «адрес или домен → тип»,
 * как фильтры Gmail и правила Front. Правило применяется к новым письмам до помощника и побеждает его; создать его можно и
 * из карточки письма. Менять — администратор.
 */
export function MailRules({ readOnly }: { readOnly: boolean }) {
  const { t, i18n } = useTranslation("letters");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const patternId = useId();
  const typeId = useId();
  const rules = useListMailSenderRules();
  const types = useListDictionaryItems("mail-types", undefined, { query: { staleTime: 60_000 } });
  const [pattern, setPattern] = useState("");
  const [typeCode, setTypeCode] = useState<string | null>(null);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: getListMailSenderRulesQueryKey() });
  };
  const add = useCreateMailSenderRule({
    mutation: {
      onSuccess: () => {
        refresh();
        setPattern("");
        void message.success(t("settings.dict.rules.added"));
      },
    },
  });
  const remove = useDeleteMailSenderRule({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("settings.dict.rules.deleted"));
      },
    },
  });
  const typeName = (code: string) => {
    const found = types.data?.items.find((item) => item.code === code);
    return found ? localName(found.name, i18n.language) : code;
  };
  const failure = add.error ?? remove.error;
  return (
    <div className="pf-co-body">
      <TabHeader title={t("settings.dict.rules.title")} hint={t("settings.dict.rules.hint")} />
      {readOnly ? null : (
        <div className="pf-co-actions">
          <div>
            <label htmlFor={patternId}>{t("settings.dict.rules.pattern")}</label>
            <Input
              id={patternId}
              value={pattern}
              maxLength={255}
              autoComplete="off"
              placeholder={t("settings.dict.rules.patternHint")}
              onChange={(event) => {
                setPattern(event.target.value);
              }}
            />
          </div>
          <div>
            <label htmlFor={typeId}>{t("settings.dict.rules.type")}</label>
            <Select
              id={typeId}
              style={{ minWidth: 240 }}
              value={typeCode}
              placeholder={t("settings.dict.choose")}
              options={(types.data?.items ?? []).map((item) => ({
                value: item.code,
                label: localName(item.name, i18n.language),
              }))}
              onChange={setTypeCode}
            />
          </div>
          <Button
            type="primary"
            loading={add.isPending}
            disabled={pattern.trim().length < 3 || typeCode === null}
            onClick={() => {
              if (typeCode) add.mutate({ data: { pattern: pattern.trim(), type_code: typeCode } });
            }}
          >
            {t("settings.dict.rules.add")}
          </Button>
        </div>
      )}
      {failure ? (
        <Alert type="error" showIcon role="alert" message={ruleError(t, failure)} />
      ) : null}
      {rules.isError ? (
        <Alert type="error" showIcon role="alert" message={t("settings.dict.rules.errors.load")} />
      ) : null}
      <ListTable<MailSenderRule>
        label={t("settings.dict.rules.title")}
        data={rules.data?.items ?? []}
        loading={rules.isPending}
        rowKey={(row) => String(row.id)}
        empty={{
          title: t("settings.dict.rules.empty.title"),
          text: t("settings.dict.rules.empty.text"),
        }}
        columns={[
          {
            title: t("settings.dict.rules.pattern"),
            key: "pattern",
            render: (_: unknown, row) => <b>{row.pattern}</b>,
          },
          {
            title: t("settings.dict.rules.type"),
            key: "type",
            render: (_: unknown, row) => typeName(row.type_code),
          },
          {
            title: t("settings.dict.rules.createdBy"),
            key: "by",
            render: (_: unknown, row) => row.created_by ?? "—",
          },
          {
            title: t("settings.dict.actions"),
            key: "actions",
            render: (_: unknown, row) => (
              <Button
                type="link"
                size="small"
                danger
                disabled={readOnly}
                loading={remove.isPending && remove.variables.id === row.id}
                aria-label={t("settings.dict.rules.deleteNamed", { pattern: row.pattern })}
                onClick={() => {
                  add.reset();
                  remove.mutate({ id: row.id });
                }}
              >
                {t("settings.dict.rules.delete")}
              </Button>
            ),
          },
        ]}
      />
    </div>
  );
}
