import {
  BoldOutlined,
  FontSizeOutlined,
  ItalicOutlined,
  LinkOutlined,
  OrderedListOutlined,
  TableOutlined,
  UnderlineOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { Button, Input, Tooltip } from "antd";
import { TableKit } from "@tiptap/extension-table";
import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { BodyNode } from "./bodyModel";

import "./body-editor.css";

export interface BodyEditorProps {
  /** id области текста: подпись формы и фокус по ошибке ведут сюда */
  id: string;
  /** Имя поля для скринридера (видимая подпись — над полем) */
  label: string;
  value: BodyNode;
  onChange: (next: BodyNode) => void;
  invalid?: boolean;
  describedBy?: string | undefined;
  disabled?: boolean;
}

const EXTENSIONS = [
  StarterKit.configure({
    heading: { levels: [1, 2, 3] },
    blockquote: false,
    code: false,
    codeBlock: false,
    horizontalRule: false,
    strike: false,
    link: { openOnClick: false, autolink: true, protocols: ["mailto", "tel"] },
  }),
  TableKit.configure({ table: { resizable: false } }),
];

/**
 * Редактор тела документа (план 2026-11-12 п. 1.2): документ сразу виден оформленным — заголовки, списки, таблица,
 * жирный, курсив, подчёркивание, ссылки; набор как в заметках (`# `, `- `, `1. `, `**текст**`). Цветов и шрифтов нет —
 * их задаёт бланк. Хранится то же дерево ProseMirror, что и в теле контракта (`bodyModel.normalizeDoc`).
 */
export function BodyEditor({
  id,
  label,
  value,
  onChange,
  invalid = false,
  describedBy,
  disabled = false,
}: BodyEditorProps) {
  const { t } = useTranslation("ui");
  const editor = useEditor({
    extensions: EXTENSIONS,
    content: value,
    editable: !disabled,
    editorProps: {
      attributes: {
        id,
        role: "textbox",
        "aria-multiline": "true",
        "aria-label": label,
        class: "pf-body-editor-content",
      },
    },
    onUpdate: ({ editor: current }) => {
      onChange(current.getJSON() as BodyNode);
    },
  });

  // Атрибуты, которые меняются после создания: ошибка и подсказки.
  useEffect(() => {
    editor.setEditable(!disabled);
    editor.setOptions({
      editorProps: {
        attributes: {
          id,
          role: "textbox",
          "aria-multiline": "true",
          "aria-label": label,
          class: "pf-body-editor-content",
          ...(invalid ? { "aria-invalid": "true" } : {}),
          ...(describedBy ? { "aria-describedby": describedBy } : {}),
        },
      },
    });
  }, [editor, id, label, invalid, describedBy, disabled]);

  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      heading: e.isActive("heading"),
      bold: e.isActive("bold"),
      italic: e.isActive("italic"),
      underline: e.isActive("underline"),
      bullet: e.isActive("bulletList"),
      ordered: e.isActive("orderedList"),
      table: e.isActive("table"),
      link: e.isActive("link"),
    }),
  });
  const [linkOpen, setLinkOpen] = useState(false);
  const [href, setHref] = useState("");

  const chain = () => editor.chain().focus();
  const tool = (key: string, active: boolean, onClick: () => void, glyph: ReactNode) => (
    <Tooltip title={t(`bodyEditor.tools.${key}`)} key={key}>
      <button
        type="button"
        className="pf-body-tool"
        aria-label={t(`bodyEditor.tools.${key}`)}
        aria-pressed={active}
        disabled={disabled}
        onClick={onClick}
      >
        {glyph}
      </button>
    </Tooltip>
  );

  return (
    <div className="pf-body-editor" data-invalid={invalid || undefined}>
      <div role="toolbar" aria-label={t("bodyEditor.toolbar")} className="pf-body-toolbar">
        {tool(
          "heading",
          state.heading,
          () => chain().toggleHeading({ level: 2 }).run(),
          <FontSizeOutlined />,
        )}
        {tool("bold", state.bold, () => chain().toggleBold().run(), <BoldOutlined />)}
        {tool("italic", state.italic, () => chain().toggleItalic().run(), <ItalicOutlined />)}
        {tool(
          "underline",
          state.underline,
          () => chain().toggleUnderline().run(),
          <UnderlineOutlined />,
        )}
        {tool(
          "bullet",
          state.bullet,
          () => chain().toggleBulletList().run(),
          <UnorderedListOutlined />,
        )}
        {tool(
          "ordered",
          state.ordered,
          () => chain().toggleOrderedList().run(),
          <OrderedListOutlined />,
        )}
        {tool(
          "table",
          state.table,
          () => chain().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
          <TableOutlined />,
        )}
        {tool(
          "link",
          state.link || linkOpen,
          () => {
            setHref(String(editor.getAttributes("link")["href"] ?? ""));
            setLinkOpen((open) => !open);
          },
          <LinkOutlined />,
        )}
      </div>
      {linkOpen ? (
        <div className="pf-body-link">
          <Input
            size="small"
            aria-label={t("bodyEditor.link.label")}
            placeholder="https://"
            value={href}
            onChange={(event) => {
              setHref(event.target.value);
            }}
          />
          <Button
            size="small"
            type="primary"
            onClick={() => {
              const value = href.trim();
              if (value) chain().extendMarkRange("link").setLink({ href: value }).run();
              else chain().extendMarkRange("link").unsetLink().run();
              setLinkOpen(false);
            }}
          >
            {t("bodyEditor.link.apply")}
          </Button>
        </div>
      ) : null}
      {state.table ? (
        <div
          className="pf-body-table-actions"
          role="group"
          aria-label={t("bodyEditor.tableActions")}
        >
          <Button size="small" onClick={() => chain().addRowAfter().run()}>
            {t("bodyEditor.addRow")}
          </Button>
          <Button size="small" onClick={() => chain().addColumnAfter().run()}>
            {t("bodyEditor.addColumn")}
          </Button>
          <Button size="small" onClick={() => chain().deleteRow().run()}>
            {t("bodyEditor.removeRow")}
          </Button>
          <Button size="small" onClick={() => chain().deleteColumn().run()}>
            {t("bodyEditor.removeColumn")}
          </Button>
          <Button size="small" danger onClick={() => chain().deleteTable().run()}>
            {t("bodyEditor.removeTable")}
          </Button>
          <span className="pf-hint">{t("bodyEditor.tableHint")}</span>
        </div>
      ) : null}
      <EditorContent editor={editor} />
    </div>
  );
}
