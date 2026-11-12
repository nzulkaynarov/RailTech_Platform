/**
 * Модель тела документа (P4, D-DOC1; редактор Tiptap — план 2026-11-12 п. 1.2): редактор хранит дерево ProseMirror, перед
 * сохранением оно приводится к схеме тела `packages/contracts/documents/body.schema.json`: только известные узлы, атрибуты
 * и метки; цветов, шрифтов и HTML в теле нет — оформление задаёт бланк. Незнакомый узел становится абзацем с его текстом.
 */

export type BodyLang = "ru" | "uz" | "en";

/** Узел тела: дерево ProseMirror; поля — по схеме тела. */
export interface BodyNode {
  type: string;
  attrs?: Record<string, unknown>;
  content?: BodyNode[];
  text?: string;
  marks?: { type: string; attrs?: Record<string, unknown> }[];
}

export interface Body {
  version: 1;
  lang: BodyLang;
  page?: Record<string, unknown>;
  doc: { [key: string]: unknown };
}

/** Предел колонок и строк таблицы — как в схеме тела (20 колонок, 500 строк). */
export const MAX_COLUMNS = 20;
export const MAX_ROWS = 500;

const LINK = /^(https?:\/\/|mailto:|tel:)[^\s<>"']+$/;
const ALIGN = new Set(["left", "center", "right", "justify"]);
const SIMPLE_MARKS = new Set(["bold", "italic", "underline"]);

export function emptyDoc(): BodyNode {
  return { type: "doc", content: [{ type: "paragraph" }] };
}

export function bodyLang(language: string): BodyLang {
  const code = language.slice(0, 2).toLowerCase();
  return code === "uz" || code === "en" ? code : "ru";
}

/** Абзац из простого текста: перевод строки — `hardBreak`. */
export function paragraphOf(text: string): BodyNode {
  const content: BodyNode[] = [];
  text.split("\n").forEach((line, index) => {
    if (index > 0) content.push({ type: "hardBreak" });
    if (line !== "") content.push({ type: "text", text: line });
  });
  return content.length > 0 ? { type: "paragraph", content } : { type: "paragraph" };
}

function nodeText(node: BodyNode | undefined): string {
  if (!node) return "";
  if (node.type === "text") return node.text ?? "";
  if (node.type === "hardBreak") return "\n";
  if (node.type === "variable") return "";
  return (node.content ?? []).map(nodeText).join("");
}

function children(node: unknown): BodyNode[] {
  if (typeof node !== "object" || node === null) return [];
  const content = (node as { content?: unknown }).content;
  return Array.isArray(content) ? (content as BodyNode[]) : [];
}

function marksOf(node: BodyNode): BodyNode["marks"] {
  const marks = (node.marks ?? []).flatMap((mark) => {
    if (SIMPLE_MARKS.has(mark.type)) return [{ type: mark.type }];
    const href = mark.attrs?.["href"];
    if (
      mark.type === "link" &&
      typeof href === "string" &&
      LINK.test(href) &&
      href.length <= 2000
    ) {
      return [{ type: "link", attrs: { href } }];
    }
    return [];
  });
  return marks.length > 0 ? marks.slice(0, 4) : undefined;
}

function inlineNodes(nodes: BodyNode[]): BodyNode[] {
  const out = nodes.flatMap((node): BodyNode[] => {
    if (node.type === "hardBreak") return [{ type: "hardBreak" }];
    if (node.type === "text") {
      if (!node.text) return [];
      const marks = marksOf(node);
      return [{ type: "text", text: node.text, ...(marks ? { marks } : {}) }];
    }
    const text = nodeText(node);
    return text ? [{ type: "text", text }] : [];
  });
  // Висящий перевод строки в конце абзаца ничего не печатает.
  while (out.length > 0 && out[out.length - 1]?.type === "hardBreak") out.pop();
  return out;
}

function alignAttrs(node: BodyNode): Record<string, unknown> {
  const align = node.attrs?.["textAlign"];
  return typeof align === "string" && ALIGN.has(align) && align !== "left"
    ? { textAlign: align }
    : {};
}

function paragraph(node: BodyNode): BodyNode {
  const content = inlineNodes(children(node));
  const attrs = alignAttrs(node);
  return {
    type: "paragraph",
    ...(Object.keys(attrs).length > 0 ? { attrs } : {}),
    ...(content.length > 0 ? { content } : {}),
  };
}

function list(node: BodyNode): BodyNode | null {
  const items = children(node).flatMap((item): BodyNode[] => {
    const content = children(item).flatMap((child): BodyNode[] => {
      if (child.type === "bulletList" || child.type === "orderedList") {
        const nested = list(child);
        return nested ? [nested] : [];
      }
      return [paragraph(child)];
    });
    if (!content.some((child) => child.type !== "paragraph" || child.content)) return [];
    return [
      {
        type: "listItem",
        content: content[0]?.type === "paragraph" ? content : [{ type: "paragraph" }, ...content],
      },
    ];
  });
  if (items.length === 0) return null;
  const start = node.attrs?.["start"];
  const attrs =
    node.type === "orderedList" && typeof start === "number" && start > 1 ? { start } : null;
  return { type: node.type, ...(attrs ? { attrs } : {}), content: items };
}

function cell(node: BodyNode): BodyNode {
  const attrs: Record<string, unknown> = {};
  for (const key of ["colspan", "rowspan"] as const) {
    const value = node.attrs?.[key];
    if (typeof value === "number" && value > 1) attrs[key] = value;
  }
  const align = node.attrs?.["align"];
  if (align === "center" || align === "right") attrs["align"] = align;
  const paragraphs = children(node).map((child) =>
    child.type === "paragraph" ? paragraph(child) : paragraphOf(nodeText(child)),
  );
  return {
    type: node.type === "tableHeader" ? "tableHeader" : "tableCell",
    ...(Object.keys(attrs).length > 0 ? { attrs } : {}),
    content: paragraphs.length > 0 ? paragraphs : [{ type: "paragraph" }],
  };
}

function table(node: BodyNode): BodyNode | null {
  const rows = children(node)
    .slice(0, MAX_ROWS)
    .map((row) => ({ type: "tableRow", content: children(row).slice(0, MAX_COLUMNS).map(cell) }))
    .filter((row) => row.content.length > 0);
  if (!rows.some((row) => row.content.some((c) => nodeText(c).trim() !== ""))) return null;
  return { type: "table", attrs: { variant: "grid" }, content: rows };
}

function block(node: BodyNode): BodyNode | null {
  switch (node.type) {
    case "paragraph":
      return paragraph(node);
    case "heading": {
      const level = node.attrs?.["level"];
      const content = inlineNodes(children(node));
      if (content.length === 0) return null;
      return {
        type: "heading",
        attrs: { level: level === 1 || level === 2 ? level : 3, ...alignAttrs(node) },
        content,
      };
    }
    case "bulletList":
    case "orderedList":
      return list(node);
    case "table":
      return table(node);
    default: {
      const text = nodeText(node);
      return text.trim() ? paragraphOf(text) : null;
    }
  }
}

/** Дерево редактора → узлы тела по схеме; пустые абзацы в начале и в конце отбрасываются. */
export function normalizeDoc(doc: BodyNode | null | undefined): BodyNode {
  const content = children(doc).flatMap((node) => {
    const out = block(node);
    return out ? [out] : [];
  });
  const filled = (node: BodyNode) => node.type !== "paragraph" || Boolean(node.content);
  while (content.length > 0 && !filled(content[0] as BodyNode)) content.shift();
  while (content.length > 0 && !filled(content[content.length - 1] as BodyNode)) content.pop();
  return { type: "doc", content };
}

/** Дерево редактора → тело контракта. */
export function toBody(doc: BodyNode, lang: BodyLang): Body {
  return { version: 1, lang, doc: normalizeDoc(doc) as unknown as Body["doc"] };
}

/** В теле нет текста: пробелы и пустые таблицы не считаются. */
export function isBlank(doc: BodyNode): boolean {
  return bodyText(toBody(doc, "ru")).trim() === "";
}

/** Тело (сохранённый черновик) → дерево редактора; пустое — один пустой абзац. */
export function fromBody(body: Body | null | undefined): BodyNode {
  const doc = normalizeDoc(body?.doc as BodyNode | undefined);
  return (doc.content ?? []).length > 0 ? doc : emptyDoc();
}

/**
 * Плоский текст тела (поле `text` документа — поиск и показ без PDF): абзацы через пустую строку, пункты списка с «•» или
 * номером, строки таблицы — ячейки через « | ».
 */
export function bodyText(body: Body): string {
  return children(body.doc)
    .map((node) => {
      if (node.type === "bulletList" || node.type === "orderedList") {
        return children(node)
          .map(
            (item, i) =>
              `${node.type === "bulletList" ? "•" : `${String(i + 1)}.`} ${nodeText(item)}`,
          )
          .join("\n");
      }
      if (node.type === "table") {
        return children(node)
          .map((row) =>
            children(row)
              .map((c) => nodeText(c))
              .join(" | "),
          )
          .join("\n");
      }
      return nodeText(node);
    })
    .filter((part) => part.trim() !== "")
    .join("\n\n");
}
