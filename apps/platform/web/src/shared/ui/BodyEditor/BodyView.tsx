import type { ReactNode } from "react";

import { type Body, type BodyNode, normalizeDoc } from "./bodyModel";

import "./body-editor.css";

export interface BodyViewProps {
  /** Тело документа на бланке (контракт `documents/body.schema.json`) */
  body: Body;
  /** Подпись таблиц для скринридера */
  tableLabel?: string;
}

function inline(nodes: BodyNode[] | undefined): ReactNode[] {
  return (nodes ?? []).map((node, index) => {
    if (node.type === "hardBreak") return <br key={index} />;
    let out: ReactNode = node.text ?? "";
    for (const mark of node.marks ?? []) {
      if (mark.type === "bold") out = <strong>{out}</strong>;
      else if (mark.type === "italic") out = <em>{out}</em>;
      else if (mark.type === "underline") out = <u>{out}</u>;
      else if (mark.type === "link" && typeof mark.attrs?.["href"] === "string") {
        out = (
          <a href={mark.attrs["href"]} target="_blank" rel="noreferrer noopener">
            {out}
          </a>
        );
      }
    }
    return <span key={index}>{out}</span>;
  });
}

function blockView(node: BodyNode, key: number, tableLabel?: string): ReactNode {
  switch (node.type) {
    case "paragraph":
      return (
        <p key={key} className="pf-body-view-p">
          {inline(node.content)}
        </p>
      );
    case "heading": {
      const level = node.attrs?.["level"] === 1 ? 3 : node.attrs?.["level"] === 2 ? 4 : 5;
      const Tag = `h${String(level)}` as "h3" | "h4" | "h5";
      return (
        <Tag key={key} className="pf-body-view-h">
          {inline(node.content)}
        </Tag>
      );
    }
    case "bulletList":
    case "orderedList": {
      const Tag = node.type === "bulletList" ? "ul" : "ol";
      return (
        <Tag key={key} className="pf-body-view-list">
          {(node.content ?? []).map((item, index) => (
            <li key={index}>
              {(item.content ?? []).map((child, i) => blockView(child, i, tableLabel))}
            </li>
          ))}
        </Tag>
      );
    }
    case "table":
      return (
        <div key={key} className="pf-body-view-table-wrap">
          <table className="pf-body-view-table" aria-label={tableLabel}>
            <tbody>
              {(node.content ?? []).map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {(row.content ?? []).map((cell, index) => {
                    const Tag = cell.type === "tableHeader" ? "th" : "td";
                    return (
                      <Tag key={index} scope={Tag === "th" ? "col" : undefined}>
                        {(cell.content ?? []).map((p, i) => blockView(p, i, tableLabel))}
                      </Tag>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    default:
      return null;
  }
}

/**
 * Тело документа для чтения (карточка письма): те же узлы, что сохраняет редактор, — абзацы, заголовки, списки, таблица
 * с шапкой, выделение текста и ссылки. Разбор — общий (`normalizeDoc`), поэтому чтение и правка не расходятся.
 */
export function BodyView({ body, tableLabel }: BodyViewProps) {
  const doc = normalizeDoc(body.doc as unknown as BodyNode);
  return (
    <div className="pf-body-view">
      {(doc.content ?? []).map((node, index) => blockView(node, index, tableLabel))}
    </div>
  );
}
