/** Копирование текста в буфер. Нет буфера или разрешения (адрес без https) — `false`: интерфейс скажет об этом словами. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Ссылка «Открыть в почте»: письмо составляет сам сотрудник, получателя не подставляем и ничего не отправляем. */
export function mailtoLink(subject: string, body: string): string {
  return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

/** Ссылка «Открыть в Telegram»: окно выбора адресата с готовым текстом, отправляет сотрудник. */
export function telegramShareLink(text: string): string {
  return `https://t.me/share/url?url=%20&text=${encodeURIComponent(text)}`;
}
