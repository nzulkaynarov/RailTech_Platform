/**
 * Клавиши в поле ответа лиду (дизайн-аудит 2026-10-11, отчёт 2):
 * десктоп — Enter или Ctrl/Cmd+Enter отправляет, Shift+Enter — новая строка;
 * телефон/планшет (сенсорный ввод) — Enter всегда новая строка, отправка только кнопкой
 * (на экранной клавиатуре нет Shift+Enter); Ctrl/Cmd+Enter отправляет везде.
 */
export type ChatKey = {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  /** Идёт набор через IME (составной символ) — Enter подтверждает его, а не отправляет. */
  isComposing?: boolean;
};

export type ChatKeyAction = "send" | "newline" | "none";

export function chatKeyAction(event: ChatKey, touch: boolean): ChatKeyAction {
  if (event.key !== "Enter" || event.isComposing) return "none";
  if (event.ctrlKey || event.metaKey) return "send";
  if (touch) return "newline";
  if (event.shiftKey) return "newline";
  return "send";
}

/** Язык сообщения для атрибута `lang`: сообщения лида — на языке лида (WCAG 3.1.2). */
export function messageLang(role: string, leadLanguage: string | undefined): string | undefined {
  if (role !== "lead" || !leadLanguage) return undefined;
  const lang = leadLanguage.toLowerCase();
  return ["ru", "uz", "en"].includes(lang) ? lang : undefined;
}
