/** Почта: одна, без пробелов, с «@» и точкой в домене (точную проверку делает сервер) — для отметок шагов форм. */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isEmailLike(value: string | null | undefined): boolean {
  return EMAIL.test((value ?? "").trim());
}
