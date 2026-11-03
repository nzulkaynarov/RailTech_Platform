import { Alert, Button, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ImapFolder } from "../../../shared/api/generated/model";
import { useFindImapFolders } from "../../../shared/api/generated/platform-bff";
import type { FolderChoice } from "./folderChoice";
import { ErrorNote, Field } from "./parts";

/**
 * Папки опроса в форме приёма: «Найти папки» — список ящика (IMAP `LIST`) с подсказкой «Спам» по флагу `\Junk`;
 * названия у провайдеров разные, поэтому выбор — из ответа сервера, а не из списка в коде.
 */
export function InboundFolders({
  known,
  value,
  onChange,
  canFind,
}: {
  known: readonly ImapFolder[];
  value: FolderChoice;
  onChange: (next: FolderChoice) => void;
  canFind: boolean;
}) {
  const { t, i18n } = useTranslation("integrations");
  const [labels, setLabels] = useState<Record<string, string>>(() =>
    Object.fromEntries(known.map((f) => [f.name, f.label])),
  );
  const find = useFindImapFolders({
    mutation: {
      onSuccess: (data) => {
        if (!data.ok) return;
        const selectable = data.folders.filter((f) => f.selectable);
        setLabels((prev) => ({
          ...prev,
          ...Object.fromEntries(selectable.map((f) => [f.name, f.label])),
        }));
        if (!value.spam && data.spam_suggestion) {
          const spam = data.spam_suggestion;
          onChange({ regular: value.regular.filter((name) => name !== spam), spam });
        }
      },
    },
  });
  const names = Array.from(
    new Set([...Object.keys(labels), ...value.regular, ...(value.spam ? [value.spam] : [])]),
  );
  const option = (name: string) => ({ value: name, label: labels[name] ?? name });
  const reasonKey = `mail.inbound.reason.${find.data?.error_kind ?? "unavailable"}`;
  return (
    <>
      <Field
        id="imap-folders"
        label={t("mail.inbound.folders")}
        hint={t("mail.inbound.foldersHint")}
      >
        <Select
          id="imap-folders"
          mode="multiple"
          value={value.regular}
          options={names.filter((name) => name !== value.spam).map(option)}
          onChange={(regular: string[]) => {
            onChange({ ...value, regular });
          }}
        />
      </Field>
      <Field id="imap-spam-folder" label={t("mail.inbound.spamFolder")}>
        <Select
          id="imap-spam-folder"
          value={value.spam ?? ""}
          options={[
            { value: "", label: t("mail.inbound.spamNone") },
            ...names.filter((name) => !value.regular.includes(name)).map(option),
          ]}
          onChange={(spam: string) => {
            onChange({ ...value, spam: spam || null });
          }}
        />
      </Field>
      <div className="pf-int-row">
        <Button
          loading={find.isPending}
          disabled={!canFind}
          onClick={() => {
            find.mutate();
          }}
        >
          {t("mail.inbound.find")}
        </Button>
      </div>
      {find.data ? (
        <Alert
          type={find.data.ok ? "success" : "error"}
          showIcon
          role="status"
          message={
            find.data.ok
              ? t("mail.inbound.findOk", { count: find.data.folders.length })
              : i18n.exists(reasonKey, { ns: "integrations" })
                ? t(reasonKey)
                : (find.data.error_kind ?? "")
          }
        />
      ) : null}
      <ErrorNote error={find.error} />
    </>
  );
}
