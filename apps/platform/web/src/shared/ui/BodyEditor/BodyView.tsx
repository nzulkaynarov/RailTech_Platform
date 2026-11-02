import type { Body } from "./bodyModel";
import { fromBody } from "./bodyModel";

import "./body-editor.css";

export interface BodyViewProps {
  /** Тело документа на бланке (контракт `documents/body.schema.json`) */
  body: Body;
  /** Подпись таблиц для скринридера */
  tableLabel?: string;
}

/**
 * Тело документа для чтения (карточка письма): те же блоки, что в редакторе P4 (`BodyEditor`), — абзацы, маркированный и
 * нумерованный список, таблица с шапкой из первой строки, как в PDF. Разбор узлов — один (`fromBody`), поэтому чтение и
 * правка не расходятся; незнакомые узлы — абзацы с их текстом, пустые блоки не показываются.
 */
export function BodyView({ body, tableLabel }: BodyViewProps) {
  const blocks = fromBody(body).filter((block) => {
    if (block.kind === "paragraph") return block.text.trim() !== "";
    if (block.kind === "table")
      return block.rows.some((row) => row.some((cell) => cell.trim() !== ""));
    return block.items.some((item) => item.trim() !== "");
  });
  return (
    <div className="pf-body-view">
      {blocks.map((block) => {
        if (block.kind === "paragraph") {
          return (
            <p key={block.id} className="pf-body-view-p">
              {block.text}
            </p>
          );
        }
        if (block.kind !== "table") {
          const Tag = block.kind === "bullet" ? "ul" : "ol";
          return (
            <Tag key={block.id} className="pf-body-view-list">
              {block.items
                .filter((item) => item.trim() !== "")
                .map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
            </Tag>
          );
        }
        const [head = [], ...rows] = block.rows;
        return (
          <div key={block.id} className="pf-body-view-table-wrap">
            <table className="pf-body-view-table" aria-label={tableLabel}>
              <thead>
                <tr>
                  {head.map((cell, index) => (
                    <th key={index} scope="col">
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, index) => (
                      <td key={index}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
