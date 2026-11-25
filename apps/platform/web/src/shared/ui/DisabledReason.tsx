/**
 * Причина неактивной кнопки (Б-2): одна короткая строка рядом с кнопкой, пока действие недоступно; кнопка ссылается на
 * неё через `aria-describedby`. Нет причины — нет строки.
 */
export function DisabledReason({ id, children }: { id: string; children?: string | null }) {
  if (!children) return null;
  return (
    <p id={id} className="pf-hint pf-disabled-reason">
      {children}
    </p>
  );
}
