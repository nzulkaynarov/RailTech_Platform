import { t } from "../i18n/ru";

/** Куда ведёт объект аудита/ссылки: у лида и клиента есть карточки, у остального — раздел. */
export function entityPath(type: string, id: number | string | null | undefined): string | null {
  switch (type) {
    case "lead":
      return id ? `/leads/${String(id)}` : "/leads";
    case "client":
      return id ? `/clients/${String(id)}` : "/clients";
    case "user":
      return "/users";
    case "kb_document":
    case "product":
      return "/kb";
    case "kb_gap":
      return "/gaps";
    case "settings":
      return "/settings";
    default:
      return null;
  }
}

/** Текст ссылки на лида: `#id · имя` (без имени в данных — `#id`; пустое имя — «—»). */
export function leadLinkText(id: number | string, name?: string | null): string {
  if (name === undefined) return `#${String(id)}`;
  return `#${String(id)} · ${name || t.common.none}`;
}
