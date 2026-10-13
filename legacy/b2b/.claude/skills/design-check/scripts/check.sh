#!/usr/bin/env bash
# Детерминированный поиск нарушений дизайн-системы RailTech в .tsx.
# Использование:
#   check.sh                 — изменённые (git) .tsx
#   check.sh --all           — весь frontend/src
#   check.sh <файлы/папки>   — явный скоуп
# Печатает "FILE:LINE: совпадение" по секциям; исправляет НЕ скрипт, а ревьюер.
set -uo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

if ! command -v rg >/dev/null 2>&1; then
  echo "ERROR: ripgrep (rg) не найден — brew install ripgrep" >&2
  exit 1
fi

if [ "${1:-}" = "--all" ]; then
  RAW=$(rg --files frontend/src -g '*.tsx' 2>/dev/null)
elif [ $# -gt 0 ]; then
  RAW=$(for arg in "$@"; do
    if [ -d "$arg" ]; then rg --files "$arg" -g '*.tsx' 2>/dev/null; else echo "$arg"; fi
  done)
else
  RAW=$( (git diff --name-only HEAD 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null) | grep -E '\.tsx$' | sort -u )
fi

# Исключения: shadcn-примитивы, тесты
FILES=$(printf '%s\n' "$RAW" \
  | grep -v 'components/ui/' \
  | grep -v '\.test\.tsx$' \
  | grep -v 'src/test/' \
  | while read -r f; do [ -f "$f" ] && echo "$f"; done)

if [ -z "$FILES" ]; then
  echo "Скоуп пуст: нет .tsx файлов для проверки."
  exit 0
fi

found=0
chk() { # chk <заголовок> <regex...>
  local title="$1"; shift
  local out
  out=$(printf '%s\n' "$FILES" | tr '\n' '\0' | xargs -0 rg -nH --no-heading "$@" 2>/dev/null)
  if [ -n "$out" ]; then
    echo; echo "== $title =="
    echo "$out"
    found=1
  fi
}

chk "Палитровые цвета (заменить на семантические токены: foreground/muted/success/warning/destructive/info)" \
  -e '\b(text|bg|border|ring|fill|stroke|from|to|via)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|industrial)-[0-9]{2,3}\b'

chk "text-white / text-black (заменить на text-foreground / text-primary-foreground)" \
  -e '\btext-(white|black)\b'

chk "Hex-цвета (заменить на var(--color-chart-N) или семантический токен)" \
  -e "['\"\`(]#[0-9a-fA-F]{6}\b"

chk "Произвольные размеры текста (только шкала Tailwind, минимум text-xs)" \
  -e 'text-\[[0-9]+px\]'

chk "Raw HTML-элементы (использовать shadcn <Input>/<Textarea>/<Table>/<Select>; sidebar — shadcn <Sidebar>)" \
  -e '<(input|textarea|table|select|aside)\b'

chk "alert() (использовать toast() из sonner)" \
  -e '\balert\('

chk "dangerouslySetInnerHTML (использовать <Trans> из react-i18next)" \
  -e 'dangerouslySetInnerHTML'

chk "Inline style для статики (использовать Tailwind-классы; графики — bg-[var(--color-chart-N)])" \
  -e 'style=\{\{'

chk "Emoji в коде (использовать иконки lucide-react)" \
  -e '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}\x{2B00}-\x{2BFF}]'

echo
if [ "$found" -eq 0 ]; then
  echo "OK: нарушений дизайн-системы не найдено."
else
  echo "ГОТОВО: выше — кандидаты. Исключения возможны (например, hex в SVG-экспорте) — вердикт за ревьюером."
fi
exit 0
