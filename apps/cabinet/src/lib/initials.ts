/** Буквы плитки из названия оператора: две заглавные первого слова («RailTech» → RT), иначе первые буквы двух слов. */
export function initialsOf(name: string): string {
  const [first = '', second = ''] = name.match(/[\p{L}\p{N}]+/gu) ?? [];
  const [c1, c2] = first.match(/\p{Lu}/gu) ?? [];
  if (c1 && c2 && /\p{Ll}/u.test(first)) return `${c1}${c2}`;
  if (second === '') return first.slice(0, 2).toUpperCase();
  return `${first.slice(0, 1)}${second.slice(0, 1)}`.toUpperCase();
}
