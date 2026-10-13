/**
 * Шаблоны ответов в карточке лида (аудит 2026-10-12 §5). Чистые функции, без React и сети.
 * Текст — на языке лида (пустой → русский), подстановки {name}/{manager} заполнены.
 * Клиенту ничего не отправляется: результат вставляется в поле ответа.
 */
import type { LocalizedText, ReplyTemplateOut } from "../api/generated/model";

export type FillContext = { language: string | undefined; name: string; manager: string };

function pick(text: LocalizedText, language: string | undefined): string {
  const own = language === "uz" ? text.uz : language === "en" ? text.en : text.ru;
  return own.trim() ? own : text.ru;
}

/** Текст шаблона для лида; пустая подстановка не оставляет «висячих» пробелов и запятых. */
export function fillTemplate(text: LocalizedText, ctx: FillContext): string {
  const values: Record<string, string> = { name: ctx.name.trim(), manager: ctx.manager.trim() };
  return pick(text, ctx.language)
    .replace(/\{(name|manager)\}/g, (_, key: string) => values[key] ?? "")
    .replace(/[ \t]+([,.!?])/g, "$1")
    .replace(/,(?=[,.!?])/g, "")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

/** Вставка в поле: пустое поле — текст шаблона, иначе — с новой строки после черновика. */
export function insertIntoDraft(draft: string, text: string): string {
  return draft.trim() ? `${draft.trimEnd()}\n${text}` : text;
}

/** Поиск по названию и тексту на любом языке, без учёта регистра. */
export function searchTemplates(items: ReplyTemplateOut[], query: string): ReplyTemplateOut[] {
  const q = query.trim().toLocaleLowerCase("ru");
  if (!q) return items;
  return items.filter((item) =>
    [item.title, item.text.ru, item.text.uz, item.text.en].some((s) =>
      s.toLocaleLowerCase("ru").includes(q),
    ),
  );
}
