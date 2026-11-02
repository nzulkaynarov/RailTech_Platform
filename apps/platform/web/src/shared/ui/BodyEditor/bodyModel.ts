/**
 * Модель блочного редактора тела документа (P4, D-DOC1): блоки экрана ↔ тело контракта
 * `packages/contracts/documents/body.schema.json` (узлы ProseMirror). Редактор знает минимум исследования шаблонов §3.3 —
 * абзац, маркированный и нумерованный список, таблица (первая строка — шапка `tableHeader`, она повторяется на каждой
 * странице PDF). Цветов, шрифтов и HTML в теле нет: оформление задаёт бланк.
 */

export type BodyLang = "ru" | "uz" | "en";

export type Block =
  | { id: string; kind: "paragraph"; text: string }
  | { id: string; kind: "bullet" | "ordered"; items: string[] }
  | { id: string; kind: "table"; rows: string[][] };

export type BlockKind = Block["kind"];

/** Узел тела: дерево ProseMirror; поля — по схеме тела. */
export interface BodyNode {
  type: string;
  attrs?: Record<string, unknown>;
  content?: BodyNode[];
  text?: string;
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

let counter = 0;
export function blockId(): string {
  counter += 1;
  return `b${String(counter)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function newBlock(kind: BlockKind): Block {
  switch (kind) {
    case "paragraph":
      return { id: blockId(), kind, text: "" };
    case "bullet":
    case "ordered":
      return { id: blockId(), kind, items: [""] };
    case "table":
      return {
        id: blockId(),
        kind,
        rows: [
          ["", ""],
          ["", ""],
        ],
      };
  }
}

export function emptyBlocks(): Block[] {
  return [newBlock("paragraph")];
}

export function bodyLang(language: string): BodyLang {
  const code = language.slice(0, 2).toLowerCase();
  return code === "uz" || code === "en" ? code : "ru";
}

/** Текст строки → инлайн-узлы: перевод строки — `hardBreak`, пустое — без узлов. */
function inline(text: string): BodyNode[] {
  const nodes: BodyNode[] = [];
  text.split("\n").forEach((line, index) => {
    if (index > 0) nodes.push({ type: "hardBreak" });
    if (line !== "") nodes.push({ type: "text", text: line });
  });
  // Висящий перевод строки в конце абзаца ничего не печатает.
  while (nodes.length > 0 && nodes[nodes.length - 1]?.type === "hardBreak") nodes.pop();
  return nodes;
}

function paragraph(text: string): BodyNode {
  const content = inline(text);
  return content.length > 0 ? { type: "paragraph", content } : { type: "paragraph" };
}

function listItems(items: string[]): string[] {
  return items.map((item) => item.trim()).filter((item) => item !== "");
}

function tableRows(rows: string[][]): string[][] {
  const width = Math.max(1, ...rows.map((row) => row.length));
  const filled = rows.filter((row) => row.some((cell) => cell.trim() !== ""));
  return filled.map((row) => Array.from({ length: width }, (_, i) => (row[i] ?? "").trim()));
}

function blockNode(block: Block): BodyNode | null {
  switch (block.kind) {
    case "paragraph":
      return block.text.trim() === "" ? null : paragraph(block.text.trim());
    case "bullet":
    case "ordered": {
      const items = listItems(block.items);
      if (items.length === 0) return null;
      return {
        type: block.kind === "bullet" ? "bulletList" : "orderedList",
        content: items.map((item) => ({ type: "listItem", content: [paragraph(item)] })),
      };
    }
    case "table": {
      const rows = tableRows(block.rows);
      if (rows.length === 0) return null;
      return {
        type: "table",
        attrs: { variant: "grid" },
        content: rows.map((row, index) => ({
          type: "tableRow",
          content: row.map((cell) => ({
            type: index === 0 ? "tableHeader" : "tableCell",
            content: [paragraph(cell)],
          })),
        })),
      };
    }
  }
}

/** Блоки → тело контракта; пустые блоки отбрасываются. */
export function toBody(blocks: readonly Block[], lang: BodyLang): Body {
  const content = blocks.flatMap((block) => {
    const node = blockNode(block);
    return node ? [node] : [];
  });
  return { version: 1, lang, doc: { type: "doc", content } };
}

/** В теле нет ни одного непустого блока. */
export function isBlank(blocks: readonly Block[]): boolean {
  return blocks.every((block) => blockNode(block) === null);
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

/** Тело (сохранённый черновик) → блоки редактора; незнакомые узлы становятся абзацами с их текстом. */
export function fromBody(body: Body | null | undefined): Block[] {
  if (!body) return emptyBlocks();
  const blocks: Block[] = children(body.doc).map((node): Block => {
    if (node.type === "bulletList" || node.type === "orderedList") {
      return {
        id: blockId(),
        kind: node.type === "bulletList" ? "bullet" : "ordered",
        items: children(node).map((item) => nodeText(item)),
      };
    }
    if (node.type === "table") {
      return {
        id: blockId(),
        kind: "table",
        rows: children(node).map((row) => children(row).map((cell) => nodeText(cell))),
      };
    }
    return { id: blockId(), kind: "paragraph", text: nodeText(node) };
  });
  return blocks.length > 0 ? blocks : emptyBlocks();
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
              .map((cell) => nodeText(cell))
              .join(" | "),
          )
          .join("\n");
      }
      return nodeText(node);
    })
    .filter((part) => part.trim() !== "")
    .join("\n\n");
}
