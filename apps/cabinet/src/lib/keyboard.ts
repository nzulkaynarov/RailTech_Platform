/**
 * Сочетания клавиш кабинета (CAB-FIX-3, K12): клавиша — по `event.code` (физическая клавиша), поэтому ⌘\ и ⌘S работают
 * и в русской раскладке; в полях ввода сочетания оболочки не срабатывают — там клавиши принадлежат тексту.
 */

/** Mac и iOS — ⌘, остальные — Ctrl: подсказки сочетаний пишутся так, как их видит человек. */
export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /Mac|iPhone|iPad/.test(`${navigator.platform} ${navigator.userAgent}`);
}

/** Подпись сочетания с модификатором: `shortcutLabel('S')` → «⌘S» на Mac, «Ctrl+S» на Windows. */
export function shortcutLabel(key: string): string {
  return isMacPlatform() ? `⌘${key}` : `Ctrl+${key}`;
}

/** Фокус в поле ввода текста: `input` (кроме кнопок и флажков), `textarea`, `select`, `contenteditable`. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable || target.closest('[contenteditable=""], [contenteditable="true"]')) return true;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  if (target instanceof HTMLInputElement) {
    return !['button', 'checkbox', 'radio', 'submit', 'reset', 'file', 'image', 'range', 'color'].includes(target.type);
  }
  return false;
}

/** ⌘\ / Ctrl+\ — свернуть или развернуть сайдбар; не в поле ввода. */
export function isSidebarToggle(event: KeyboardEvent): boolean {
  if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return false;
  return event.code === 'Backslash' && !isTypingTarget(event.target);
}
