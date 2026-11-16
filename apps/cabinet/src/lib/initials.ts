/** Буквы плитки из названия оператора: две заглавные первого слова («RailTech» → RT), иначе первые буквы двух слов. */
export function initialsOf(name: string): string {
  const [first = '', second = ''] = name.match(/[\p{L}\p{N}]+/gu) ?? [];
  const [c1, c2] = first.match(/\p{Lu}/gu) ?? [];
  if (c1 && c2 && /\p{Ll}/u.test(first)) return `${c1}${c2}`;
  if (second === '') return first.slice(0, 2).toUpperCase();
  return `${first.slice(0, 1)}${second.slice(0, 1)}`.toUpperCase();
}

const LEGAL_FORMS = new Set(['ооо', 'оао', 'зао', 'ао', 'пао', 'ип', 'чп', 'сп', 'уп', 'гуп', 'мчж', 'mchj', 'qk', 'xk', 'aj', 'llc', 'ltd', 'jsc', 'inc', 'gmbh', 'fe']);

/** Инициалы человека и компании для запасного вида картинки (стандарт интерфейса §12): первые буквы двух первых слов; у компании — без организационной формы и кавычек. */
export function entityInitials(name: string, company = false): string {
  const words = name
    .replace(/[«»"'“”„()]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .filter((word) => !company || !LEGAL_FORMS.has(word.toLowerCase().replace(/\.$/, '')));
  const letters = words.slice(0, 2).map((word) => Array.from(word)[0] ?? '');
  return letters.join('').toUpperCase() || '?';
}
