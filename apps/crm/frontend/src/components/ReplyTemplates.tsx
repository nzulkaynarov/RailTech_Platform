import { App as AntApp, Select } from "antd";
import { useState } from "react";

import { useReplyTemplates } from "../api/templateQueries";
import {
  type FillContext,
  fillTemplate,
  insertIntoDraft,
  searchTemplates,
} from "../domain/replyTemplates";
import { t } from "../i18n/ru";

type Props = {
  draft: string;
  setDraft: (text: string) => void;
  context: FillContext;
  disabled: boolean;
};

/** «Шаблоны» у поля ответа: выбор с поиском вставляет текст в поле — отправляет менеджер. */
export function ReplyTemplates({ draft, setDraft, context, disabled }: Props) {
  const templates = useReplyTemplates();
  const { message } = AntApp.useApp();
  const [query, setQuery] = useState("");
  const items = searchTemplates(templates.data ?? [], query);
  return (
    <Select
      showSearch
      size="small"
      className="chat-templates"
      aria-label={t.templates.pickLabel}
      placeholder={t.templates.pick}
      value={null}
      disabled={disabled}
      loading={templates.isLoading}
      filterOption={false}
      searchValue={query}
      onSearch={setQuery}
      notFoundContent={t.templates.pickEmpty}
      popupMatchSelectWidth={false}
      options={items.map((item) => ({ value: item.id, label: item.title }))}
      onSelect={(id: number | null) => {
        const item = templates.data?.find((x) => x.id === id);
        if (!item) return;
        setDraft(insertIntoDraft(draft, fillTemplate(item.text, context)));
        setQuery("");
        void message.info(t.templates.inserted);
      }}
    />
  );
}
