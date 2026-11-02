import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { Button, Input } from "antd";
import { useTranslation } from "react-i18next";

import { type Block, type BlockKind, MAX_COLUMNS, MAX_ROWS, newBlock } from "./bodyModel";

import "./body-editor.css";

const KINDS: readonly BlockKind[] = ["paragraph", "bullet", "ordered", "table"];

export interface BodyEditorProps {
  /** id первого поля ввода: подпись формы (`<label htmlFor>`) и фокус по ошибке ведут сюда */
  id: string;
  value: Block[];
  onChange: (next: Block[]) => void;
  invalid?: boolean;
  describedBy?: string | undefined;
  disabled?: boolean;
}

function TableBlock({
  block,
  index,
  fieldId,
  onChange,
  disabled,
}: {
  block: Extract<Block, { kind: "table" }>;
  index: number;
  fieldId: string | undefined;
  onChange: (rows: string[][]) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation("ui");
  const width = Math.max(1, ...block.rows.map((row) => row.length));
  const rows = block.rows.map((row) => Array.from({ length: width }, (_, i) => row[i] ?? ""));
  const set = (r: number, c: number, text: string) => {
    onChange(
      rows.map((row, ri) => (ri === r ? row.map((cell, ci) => (ci === c ? text : cell)) : row)),
    );
  };
  return (
    <div className="pf-body-table">
      <div className="pf-body-table-scroll">
        <table aria-label={t("bodyEditor.tableLabel", { n: index + 1 })}>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td key={c} className={r === 0 ? "pf-body-table-head" : undefined}>
                    <Input
                      id={r === 0 && c === 0 ? fieldId : undefined}
                      size="small"
                      value={cell}
                      maxLength={2000}
                      disabled={disabled}
                      aria-label={
                        r === 0
                          ? t("bodyEditor.headerCell", { col: c + 1 })
                          : t("bodyEditor.cell", { row: r, col: c + 1 })
                      }
                      onChange={(event) => {
                        set(r, c, event.target.value);
                      }}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pf-body-table-actions">
        <Button
          size="small"
          disabled={disabled || rows.length >= MAX_ROWS}
          onClick={() => {
            onChange([...rows, Array.from({ length: width }, () => "")]);
          }}
        >
          {t("bodyEditor.addRow")}
        </Button>
        <Button
          size="small"
          disabled={disabled || width >= MAX_COLUMNS}
          onClick={() => {
            onChange(rows.map((row) => [...row, ""]));
          }}
        >
          {t("bodyEditor.addColumn")}
        </Button>
        <Button
          size="small"
          disabled={disabled || rows.length <= 1}
          onClick={() => {
            onChange(rows.slice(0, -1));
          }}
        >
          {t("bodyEditor.removeRow")}
        </Button>
        <Button
          size="small"
          disabled={disabled || width <= 1}
          onClick={() => {
            onChange(rows.map((row) => row.slice(0, -1)));
          }}
        >
          {t("bodyEditor.removeColumn")}
        </Button>
      </div>
      <p className="pf-hint">{t("bodyEditor.tableHint")}</p>
    </div>
  );
}

/**
 * Блочный редактор тела документа на бланке (P4, D-DOC1; исследование шаблонов §3.3): абзацы, маркированный и нумерованный
 * список, таблица — блоки можно добавлять, переставлять и удалять. Без цветов и шрифтов: оформление даёт бланк, вид страницы
 * показывает настоящий PDF рядом. Модель и преобразование в тело контракта — `bodyModel.ts`.
 */
export function BodyEditor({
  id,
  value,
  onChange,
  invalid,
  describedBy,
  disabled = false,
}: BodyEditorProps) {
  const { t } = useTranslation("ui");
  const replace = (index: number, block: Block) => {
    onChange(value.map((current, i) => (i === index ? block : current)));
  };
  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= value.length) return;
    const next = [...value];
    const [item] = next.splice(index, 1);
    if (item) next.splice(target, 0, item);
    onChange(next);
  };
  const remove = (index: number) => {
    const next = value.filter((_, i) => i !== index);
    onChange(next.length > 0 ? next : [newBlock("paragraph")]);
  };
  return (
    <div className="pf-body-editor" data-invalid={invalid || undefined}>
      <ol className="pf-body-blocks" aria-label={t("bodyEditor.blocks")}>
        {value.map((block, index) => {
          const fieldId = index === 0 ? id : undefined;
          const kindLabel = t(`bodyEditor.kinds.${block.kind}`);
          const blockLabel = t("bodyEditor.blockLabel", { n: index + 1, kind: kindLabel });
          return (
            <li key={block.id} className="pf-body-block">
              <div className="pf-body-block-bar">
                <span className="pf-body-block-kind">{kindLabel}</span>
                <span className="pf-body-block-tools">
                  <Button
                    size="small"
                    type="text"
                    icon={<ArrowUpOutlined />}
                    disabled={disabled || index === 0}
                    aria-label={t("bodyEditor.moveUp", { block: blockLabel })}
                    onClick={() => {
                      move(index, -1);
                    }}
                  />
                  <Button
                    size="small"
                    type="text"
                    icon={<ArrowDownOutlined />}
                    disabled={disabled || index === value.length - 1}
                    aria-label={t("bodyEditor.moveDown", { block: blockLabel })}
                    onClick={() => {
                      move(index, 1);
                    }}
                  />
                  <Button
                    size="small"
                    type="text"
                    icon={<DeleteOutlined />}
                    disabled={disabled}
                    aria-label={t("bodyEditor.remove", { block: blockLabel })}
                    onClick={() => {
                      remove(index);
                    }}
                  />
                </span>
              </div>
              {block.kind === "paragraph" ? (
                <Input.TextArea
                  id={fieldId}
                  autoSize={{ minRows: 3, maxRows: 16 }}
                  maxLength={20000}
                  value={block.text}
                  disabled={disabled}
                  status={invalid ? "error" : undefined}
                  aria-invalid={invalid || undefined}
                  aria-label={fieldId ? undefined : blockLabel}
                  aria-describedby={fieldId ? describedBy : undefined}
                  onChange={(event) => {
                    replace(index, { ...block, text: event.target.value });
                  }}
                />
              ) : null}
              {block.kind === "bullet" || block.kind === "ordered" ? (
                <>
                  <Input.TextArea
                    id={fieldId}
                    autoSize={{ minRows: 2, maxRows: 16 }}
                    maxLength={20000}
                    value={block.items.join("\n")}
                    disabled={disabled}
                    status={invalid ? "error" : undefined}
                    aria-invalid={invalid || undefined}
                    aria-label={fieldId ? undefined : blockLabel}
                    aria-describedby={fieldId ? describedBy : undefined}
                    onChange={(event) => {
                      replace(index, { ...block, items: event.target.value.split("\n") });
                    }}
                  />
                  <p className="pf-hint">{t("bodyEditor.listHint")}</p>
                </>
              ) : null}
              {block.kind === "table" ? (
                <TableBlock
                  block={block}
                  index={index}
                  fieldId={fieldId}
                  disabled={disabled}
                  onChange={(rows) => {
                    replace(index, { ...block, rows });
                  }}
                />
              ) : null}
            </li>
          );
        })}
      </ol>
      <div className="pf-body-add" role="group" aria-label={t("bodyEditor.add")}>
        <span className="pf-hint">{t("bodyEditor.add")}</span>
        {KINDS.map((kind) => (
          <Button
            key={kind}
            size="small"
            icon={<PlusOutlined />}
            disabled={disabled}
            onClick={() => {
              onChange([...value, newBlock(kind)]);
            }}
          >
            {t(`bodyEditor.kinds.${kind}`)}
          </Button>
        ))}
      </div>
    </div>
  );
}
