/**
 * Комментарий согласующего хранится в `sessionStorage` вкладки (переживает перезагрузку, но не закрытие вкладки и не остаётся
 * на общем компьютере), пока документ не решён: ошибка решения ничего не стирает.
 */
const PREFIX = "rt-pf-memo-draft-v1";

function key(userId: string, approvalId: string): string {
  return `${PREFIX}:${userId}:${approvalId}`;
}

/** Хранилище может быть недоступно (приватное окно, заблокированные данные сайта): тогда черновика просто нет. */
export function readComment(userId: string, approvalId: string): string | null {
  try {
    return window.sessionStorage.getItem(key(userId, approvalId));
  } catch {
    return null;
  }
}

export function writeComment(userId: string, approvalId: string, comment: string): void {
  try {
    if (comment.trim() === "") window.sessionStorage.removeItem(key(userId, approvalId));
    else window.sessionStorage.setItem(key(userId, approvalId), comment);
  } catch {
    // Не критично: без хранилища введённое живёт, пока открыта страница.
  }
}

export function clearComment(userId: string, approvalId: string): void {
  try {
    window.sessionStorage.removeItem(key(userId, approvalId));
  } catch {
    // Не критично.
  }
}
