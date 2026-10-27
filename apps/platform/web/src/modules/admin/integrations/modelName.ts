/**
 * Имя модели без префикса провайдера: CRM отдаёт `anthropic/claude-haiku-5-5` (так модель названа в шлюзе), а в поле
 * «Модель» и в строке роли нужно имя у провайдера. Снимается только префикс самого провайдера роли; прочее — как есть.
 */
export function bareModelName(
  provider: string | null | undefined,
  model: string | null | undefined,
): string {
  const name = model ?? "";
  if (!provider) return name;
  const prefix = `${provider.toLowerCase()}/`;
  return name.toLowerCase().startsWith(prefix) ? name.slice(prefix.length) : name;
}
