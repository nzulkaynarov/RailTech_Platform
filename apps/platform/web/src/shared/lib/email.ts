/**
 * Почта: один шаблон и для проверки поля формы (`rules: [{ pattern: EMAIL }]`), и для отметки шага —
 * галочка и сообщение об ошибке не расходятся (Х-18). Правило то же, что у `type: "email"` в antd.
 */
export const EMAIL =
  /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;

export function isEmailLike(value: string | null | undefined): boolean {
  return EMAIL.test((value ?? "").trim());
}
