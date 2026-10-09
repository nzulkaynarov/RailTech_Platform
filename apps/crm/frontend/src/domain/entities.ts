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
