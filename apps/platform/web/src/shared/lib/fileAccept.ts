/** Подходит ли файл под `accept` (`.pdf,.png`, `image/*`, `application/json`) — для перетаскивания, где браузер не фильтрует. */
export function matchesAccept(file: File, accept: string | undefined): boolean {
  if (!accept) return true;
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  return accept
    .split(",")
    .map((token) => token.trim().toLowerCase())
    .filter(Boolean)
    .some((token) => {
      if (token.startsWith(".")) return name.endsWith(token);
      if (token.endsWith("/*")) return type.startsWith(token.slice(0, -1));
      return type === token;
    });
}

/** `accept` словами для ошибки: `.pdf,image/png` → «PDF, PNG». */
export function acceptLabel(accept: string): string {
  const labels = accept
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean)
    .map((token) => {
      if (token.startsWith(".")) return token.slice(1).toUpperCase();
      const sub = token.split("/")[1] ?? token;
      return (sub === "*" ? token : sub.replace(/\+.*$/, "")).toUpperCase();
    });
  return [...new Set(labels)].join(", ");
}
