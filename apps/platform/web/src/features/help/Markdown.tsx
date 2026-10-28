import type { ReactNode } from "react";

/**
 * Простой markdown статей помощи без `dangerouslySetInnerHTML`: заголовки `##` и `###`, абзацы, списки `-` и `1.`,
 * **жирный** и `код`. Всё остальное — обычный текст. Заголовки статьи начинаются с `h{level}`: статья внутри страницы
 * под `h1` получает `##` -> `h3` (параметр `headingLevel` задаёт уровень для `##`).
 */
function inline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const at = match.index;
    if (at > last) parts.push(text.slice(last, at));
    const token = match[0];
    parts.push(
      token.startsWith("**") ? (
        <strong key={at}>{token.slice(2, -2)}</strong>
      ) : (
        <code key={at}>{token.slice(1, -1)}</code>
      ),
    );
    last = at + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

type Block =
  | { kind: "h"; level: 2 | 3; text: string }
  | { kind: "p"; text: string }
  | { kind: "ul" | "ol"; items: string[] };

function blocks(source: string): Block[] {
  const out: Block[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length > 0) out.push({ kind: "p", text: paragraph.join(" ") });
    paragraph = [];
  };
  for (const raw of source.split("\n")) {
    const line = raw.trimEnd();
    const heading = /^(#{2,3})\s+(.*)$/.exec(line);
    const bullet = /^[-*]\s+(.*)$/.exec(line);
    const numbered = /^\d+\.\s+(.*)$/.exec(line);
    if (line.trim() === "") {
      flush();
    } else if (heading) {
      flush();
      out.push({ kind: "h", level: heading[1] === "##" ? 2 : 3, text: heading[2] ?? "" });
    } else if (bullet || numbered) {
      flush();
      const kind = bullet ? "ul" : "ol";
      const text = (bullet ?? numbered)?.[1] ?? "";
      const last = out[out.length - 1];
      if (last?.kind === kind) last.items.push(text);
      else out.push({ kind, items: [text] });
    } else {
      paragraph.push(line.trim());
    }
  }
  flush();
  return out;
}

export function Markdown({
  source,
  headingLevel = 3,
}: {
  source: string;
  headingLevel?: 2 | 3 | 4;
}) {
  return (
    <div className="pf-md">
      {blocks(source).map((block, index) => {
        if (block.kind === "h") {
          const Tag = `h${String(block.level === 2 ? headingLevel : headingLevel + 1)}` as
            "h3" | "h4" | "h5";
          return <Tag key={index}>{inline(block.text)}</Tag>;
        }
        if (block.kind === "p") return <p key={index}>{inline(block.text)}</p>;
        const List = block.kind;
        return (
          <List key={index}>
            {block.items.map((item, i) => (
              <li key={i}>{inline(item)}</li>
            ))}
          </List>
        );
      })}
    </div>
  );
}

/** Одна строка без блоков: **жирный** и `код` (пункт «Что нового», W-REL). */
export function InlineMarkdown({ text }: { text: string }) {
  return <>{inline(text)}</>;
}
