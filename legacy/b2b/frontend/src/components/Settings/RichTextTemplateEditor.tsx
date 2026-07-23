import {
  forwardRef, useEffect, useImperativeHandle, useRef, useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import {
  Bold, Italic, Heading, List, ListOrdered, Table as TableIcon, Link2, Code2,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Toggle } from '@/components/ui/toggle';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import {
  Popover, PopoverContent, PopoverTrigger,
} from '@/components/ui/popover';
import { normalizeTemplateHtml } from '@/lib/templateHtml';

/** Imperative surface the parent uses to drop a `{{code}}` placeholder at the caret. */
export interface RichTextTemplateEditorHandle {
  insertPlaceholder: (code: string) => void;
}

interface RichTextTemplateEditorProps {
  /** Normalised body HTML (source of truth in the parent). */
  value: string;
  /** Emits ALREADY-NORMALISED HTML (allowlist fixed point) in WYSIWYG mode; raw text in source mode. */
  onChange: (html: string) => void;
  /** Identity of the edited template — when it changes we reload the contentEditable from `value`. */
  templateKey: string | number;
  /** Field id for the label association. */
  id?: string;
}

// A minimal, allowlist-safe table skeleton (thead + 2 body rows, 2 cols) + a trailing paragraph so
// the caret can leave the table. Non-breaking spaces keep the empty cells clickable/visible.
const TABLE_SKELETON =
  '<table><thead><tr><th>&nbsp;</th><th>&nbsp;</th></tr></thead>' +
  '<tbody><tr><td>&nbsp;</td><td>&nbsp;</td></tr><tr><td>&nbsp;</td><td>&nbsp;</td></tr></tbody></table><p><br></p>';

const HTTP_URL_RE = /^https?:\/\//i;

function escapeForInsert(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Rich-text editor for document-template bodies (wave T2). A zero-dependency `contentEditable`
 * surface driven by `document.execCommand`, whose browser-specific output is serialised through
 * `normalizeTemplateHtml` on every change — so the saved HTML is a fixed point of the backend
 * allowlist sanitiser («what you see is what is stored»). A «HTML-исходник» toggle exposes the raw
 * markup for power users. The toolbar only offers formatting the allowlist accepts.
 */
export const RichTextTemplateEditor = forwardRef<RichTextTemplateEditorHandle, RichTextTemplateEditorProps>(
  function RichTextTemplateEditor({ value, onChange, templateKey, id }, ref) {
    const { t } = useTranslation();
    const editableRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const savedRangeRef = useRef<Range | null>(null);
    const [showSource, setShowSource] = useState(false);
    const [linkOpen, setLinkOpen] = useState(false);
    const [linkUrl, setLinkUrl] = useState('');
    const [linkError, setLinkError] = useState(false);

    // Load the DOM from `value` on template switch / mode flip. The activeElement guard prevents
    // clobbering the caret while the author is typing (value diverges from innerHTML because we store
    // the NORMALISED form, but innerHTML holds raw browser markup — never overwrite a focused editor).
    useEffect(() => {
      if (showSource) return;
      const el = editableRef.current;
      if (!el) return;
      if (document.activeElement !== el && el.innerHTML !== value) {
        el.innerHTML = value;
      }
    }, [templateKey, showSource, value]);

    function emitFromEditable() {
      const el = editableRef.current;
      if (!el) return;
      onChange(normalizeTemplateHtml(el.innerHTML));
    }

    function runCommand(command: string, argument?: string) {
      const el = editableRef.current;
      if (!el) return;
      el.focus();
      // Emit semantic tags (<strong>/<em>) instead of <span style> wrappers.
      document.execCommand('styleWithCSS', false, 'false');
      document.execCommand(command, false, argument);
      emitFromEditable();
    }

    function toggleHeading() {
      const current = document.queryCommandValue('formatBlock').toLowerCase();
      runCommand('formatBlock', current === 'h3' ? '<p>' : '<h3>');
    }

    function insertTable() {
      runCommand('insertHTML', TABLE_SKELETON);
    }

    function placeCaretAtEnd(el: HTMLElement) {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(el);
      range.collapse(false);
      selection?.removeAllRanges();
      selection?.addRange(range);
    }

    function insertIntoEditable(text: string) {
      const el = editableRef.current;
      if (!el) return;
      el.focus();
      const selection = window.getSelection();
      if (!selection || selection.rangeCount === 0 || !el.contains(selection.anchorNode)) {
        placeCaretAtEnd(el);
      }
      document.execCommand('insertText', false, text);
      emitFromEditable();
    }

    function insertIntoTextarea(text: string) {
      const textarea = textareaRef.current;
      if (!textarea) {
        onChange(value + text);
        return;
      }
      const start = textarea.selectionStart ?? value.length;
      const end = textarea.selectionEnd ?? value.length;
      const next = value.slice(0, start) + text + value.slice(end);
      onChange(next);
      requestAnimationFrame(() => {
        textarea.focus();
        const caret = start + text.length;
        textarea.setSelectionRange(caret, caret);
      });
    }

    useImperativeHandle(ref, () => ({
      insertPlaceholder(code: string) {
        const token = `{{${code}}}`;
        if (showSource) {
          insertIntoTextarea(token);
        } else {
          insertIntoEditable(token);
        }
      },
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }), [showSource, value]);

    function saveSelectionRange() {
      const selection = window.getSelection();
      if (selection && selection.rangeCount > 0 && editableRef.current?.contains(selection.anchorNode)) {
        savedRangeRef.current = selection.getRangeAt(0).cloneRange();
      } else {
        savedRangeRef.current = null;
      }
    }

    function applyLink() {
      const url = linkUrl.trim();
      if (!HTTP_URL_RE.test(url)) {
        setLinkError(true);
        return;
      }
      const el = editableRef.current;
      el?.focus();
      const selection = window.getSelection();
      if (savedRangeRef.current && selection) {
        selection.removeAllRanges();
        selection.addRange(savedRangeRef.current);
      }
      if (selection && selection.isCollapsed) {
        const safe = escapeForInsert(url);
        document.execCommand('insertHTML', false, `<a href="${safe}">${safe}</a>`);
      } else {
        document.execCommand('createLink', false, url);
      }
      emitFromEditable();
      setLinkOpen(false);
      setLinkUrl('');
      setLinkError(false);
    }

    // A toolbar button: preventDefault on mousedown keeps the editor selection alive across the click.
    function toolbarButton(
      key: string, icon: React.ReactNode, labelKey: string, onActivate: () => void,
    ) {
      const label = t(labelKey);
      return (
        <Button
          key={key}
          type="button"
          variant="ghost"
          size="icon-sm"
          onMouseDown={(event) => event.preventDefault()}
          onClick={onActivate}
          title={label}
          aria-label={label}
        >
          {icon}
        </Button>
      );
    }

    return (
      <div className="space-y-2">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-1 rounded-md border border-border bg-muted/30 p-1">
          {!showSource && (
            <>
              {toolbarButton('bold', <Bold className="size-4" />, 'richEditor.bold', () => runCommand('bold'))}
              {toolbarButton('italic', <Italic className="size-4" />, 'richEditor.italic', () => runCommand('italic'))}
              {toolbarButton('heading', <Heading className="size-4" />, 'richEditor.heading', toggleHeading)}
              <Separator orientation="vertical" className="mx-0.5 h-5" />
              {toolbarButton('ul', <List className="size-4" />, 'richEditor.bulletList', () => runCommand('insertUnorderedList'))}
              {toolbarButton('ol', <ListOrdered className="size-4" />, 'richEditor.orderedList', () => runCommand('insertOrderedList'))}
              <Separator orientation="vertical" className="mx-0.5 h-5" />
              {toolbarButton('table', <TableIcon className="size-4" />, 'richEditor.table', insertTable)}
              <Popover open={linkOpen} onOpenChange={(open) => { setLinkOpen(open); if (!open) setLinkError(false); }}>
                <PopoverTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onMouseDown={saveSelectionRange}
                    title={t('richEditor.link')}
                    aria-label={t('richEditor.link')}
                  >
                    <Link2 className="size-4" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-80 space-y-2" align="start">
                  <Label htmlFor="rich-editor-link-url" className="text-xs">{t('richEditor.linkUrl')}</Label>
                  <Input
                    id="rich-editor-link-url"
                    value={linkUrl}
                    onChange={(event) => { setLinkUrl(event.target.value); setLinkError(false); }}
                    onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); applyLink(); } }}
                    placeholder="https://example.com"
                    aria-invalid={linkError}
                  />
                  {linkError && <p className="text-xs text-destructive">{t('richEditor.linkInvalid')}</p>}
                  <div className="flex justify-end">
                    <Button type="button" size="sm" onClick={applyLink}>{t('richEditor.linkInsert')}</Button>
                  </div>
                </PopoverContent>
              </Popover>
              <Separator orientation="vertical" className="mx-0.5 h-5" />
            </>
          )}
          <Toggle
            size="sm"
            variant="outline"
            pressed={showSource}
            onPressedChange={setShowSource}
            title={t('richEditor.htmlSource')}
            aria-label={t('richEditor.htmlSource')}
            className="ml-auto gap-1.5"
          >
            <Code2 className="size-4" />
            <span className="text-xs">{t('richEditor.htmlSource')}</span>
          </Toggle>
        </div>

        {/* Editing surface */}
        {showSource ? (
          <Textarea
            id={id}
            ref={textareaRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={t('richEditor.sourcePlaceholder')}
            className="min-h-64 font-mono text-xs"
          />
        ) : (
          <div
            id={id}
            ref={editableRef}
            role="textbox"
            aria-multiline="true"
            aria-label={t('richEditor.editorLabel')}
            contentEditable
            suppressContentEditableWarning
            onInput={emitFromEditable}
            onBlur={emitFromEditable}
            className="prose prose-sm max-w-none min-h-64 rounded-md border border-input bg-transparent px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 [&_h3]:text-primary [&_table]:w-full [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1"
          />
        )}
      </div>
    );
  },
);

export default RichTextTemplateEditor;
