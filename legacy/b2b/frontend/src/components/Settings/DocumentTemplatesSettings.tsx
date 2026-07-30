import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Plus, Trash2, Loader2, FileText, Copy, Pencil, X, Info } from 'lucide-react';

import {
  useDocumentTemplates,
  useCreateTemplate,
  useUpdateTemplate,
  useDeleteTemplate,
  useCopyTemplate,
  usePreviewTemplate,
  usePlaceholderCatalog,
} from '@/hooks/useDocuments';
import type { DocumentTemplate, PlaceholderCatalogGroup, TemplatePreviewResult } from '@/api/documentsApi';
import { translateApiError } from '@/lib/apiError';
import { DocumentHtmlPreview } from '@/components/Documents/DocumentHtmlPreview';
import { SampleTemplatePreviewDialog } from '@/components/Settings/SampleTemplatePreviewDialog';
import {
  RichTextTemplateEditor,
  type RichTextTemplateEditorHandle,
} from '@/components/Settings/RichTextTemplateEditor';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';

// Document-template kinds (crm.DocumentTemplateKind lookup, spec §Данные). Compared by CODE (Rule 2).
const KIND_CODES = ['LETTER', 'REPORT', 'CUSTOM'] as const;
type KindCode = (typeof KIND_CODES)[number];
const kindLabelKey = (code: string) => `docTemplatesSettings.kind.${code.toLowerCase()}`;

const PREVIEW_DEBOUNCE_MS = 400;

interface EditorState {
  id: number | null; // null → creating a new template
  name: string;
  kind: KindCode;
  body_html: string;
}

/**
 * Company-Admin zone: manage the company's document letter/report templates (spec-documents-hub §4).
 * Benchmark: Bitrix24 template editor — a placeholder catalog whose chips insert `{{code}}` at the
 * cursor, plus a live server-rendered preview. Sample templates are read-only until copied.
 */
export function DocumentTemplatesSettings() {
  const { t } = useTranslation();
  const { data: templates = [], isLoading } = useDocumentTemplates();
  const { data: placeholderGroups = [] } = usePlaceholderCatalog();
  const createMut = useCreateTemplate();
  const updateMut = useUpdateTemplate();
  const deleteMut = useDeleteTemplate();
  const copyMut = useCopyTemplate();
  const previewMut = usePreviewTemplate();

  const [editor, setEditor] = useState<EditorState | null>(null);
  const richEditorRef = useRef<RichTextTemplateEditorHandle>(null);

  const owned = useMemo(() => templates.filter((tpl) => tpl.is_owned && !tpl.is_sample), [templates]);
  const samples = useMemo(() => templates.filter((tpl) => tpl.is_sample), [templates]);

  // Live-preview: debounce body edits, then ask the server to render (sanitised there). Depend
  // ONLY on the body — the previous `[editor, …]` dep re-fired (and re-hit the render endpoint)
  // on every name/kind keystroke, which never affects the preview.
  const previewMutate = previewMut.mutate;
  const editorBody = editor?.body_html ?? '';
  useEffect(() => {
    if (!editorBody.trim()) return;
    const handle = setTimeout(() => previewMutate(editorBody), PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [editorBody, previewMutate]);

  function startCreate() {
    setEditor({ id: null, name: '', kind: 'LETTER', body_html: '' });
    previewMut.reset();
  }

  function startEdit(tpl: DocumentTemplate) {
    const kind = (KIND_CODES as readonly string[]).includes(tpl.kind_code)
      ? (tpl.kind_code as KindCode)
      : 'CUSTOM';
    setEditor({ id: tpl.id, name: tpl.name, kind, body_html: tpl.body_html });
    previewMut.reset();
  }

  function closeEditor() {
    setEditor(null);
    previewMut.reset();
  }

  /** Insert a `{{code}}` placeholder at the caret — delegated to the rich-text editor (which knows
   *  whether it is in WYSIWYG or HTML-source mode and targets the right caret). */
  function insertPlaceholder(code: string) {
    richEditorRef.current?.insertPlaceholder(code);
  }

  async function handleSave() {
    if (!editor) return;
    if (!editor.name.trim()) {
      toast.error(translateApiError('TEMPLATE_NAME_REQUIRED'));
      return;
    }
    try {
      if (editor.id == null) {
        await createMut.mutateAsync({ name: editor.name, kind: editor.kind, body_html: editor.body_html });
        toast.success(t('docTemplatesSettings.toast.created'));
      } else {
        await updateMut.mutateAsync({
          id: editor.id,
          payload: { name: editor.name, kind: editor.kind, body_html: editor.body_html },
        });
        toast.success(t('docTemplatesSettings.toast.updated'));
      }
      closeEditor();
    } catch (err) {
      toast.error(translateApiError(err));
    }
  }

  async function handleToggleActive(tpl: DocumentTemplate) {
    try {
      await updateMut.mutateAsync({ id: tpl.id, payload: { is_active: !tpl.is_active } });
    } catch (err) {
      toast.error(translateApiError(err));
    }
  }

  async function handleDelete(tpl: DocumentTemplate) {
    try {
      await deleteMut.mutateAsync(tpl.id);
      toast.success(t('docTemplatesSettings.toast.deleted'));
      if (editor?.id === tpl.id) closeEditor();
    } catch (err) {
      toast.error(translateApiError(err));
    }
  }

  async function handleCopy(tpl: DocumentTemplate) {
    try {
      await copyMut.mutateAsync(tpl.id);
      toast.success(t('docTemplatesSettings.toast.copied'));
    } catch (err) {
      toast.error(translateApiError(err));
    }
  }

  if (isLoading) {
    return (
      <div className="flex p-10 justify-center" role="status">
        <Loader2 className="h-8 w-8 text-muted-foreground animate-spin" aria-hidden="true" />
        <span className="sr-only">{t('common.loading')}</span>
      </div>
    );
  }

  const isSaving = createMut.isPending || updateMut.isPending;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
            <FileText className="h-5 w-5 text-primary" aria-hidden="true" />
            {t('docTemplatesSettings.title')}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">{t('docTemplatesSettings.subtitle')}</p>
        </div>
        {!editor && (
          <Button onClick={startCreate}>
            <Plus className="size-4" />
            {t('docTemplatesSettings.newTemplate')}
          </Button>
        )}
      </div>

      {editor && (
        <TemplateEditor
          editor={editor}
          onChange={setEditor}
          onClose={closeEditor}
          onSave={handleSave}
          onInsert={insertPlaceholder}
          richEditorRef={richEditorRef}
          placeholderGroups={placeholderGroups}
          preview={previewMut.data}
          isPreviewing={previewMut.isPending}
          isSaving={isSaving}
        />
      )}

      {/* My templates */}
      <section className="space-y-3">
        <h4 className="text-base font-bold text-foreground">{t('docTemplatesSettings.myTemplates')}</h4>
        {owned.length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center text-sm text-muted-foreground">
              {t('docTemplatesSettings.emptyOwned')}
            </CardContent>
          </Card>
        ) : (
          <ul className="space-y-2" aria-label={t('docTemplatesSettings.myTemplates')}>
            {owned.map((tpl) => (
              <li key={tpl.id}>
                <Card>
                  <CardContent className="flex flex-wrap items-center gap-3 p-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-foreground">{tpl.name}</span>
                        <Badge variant="outline" className="shrink-0">
                          {t(kindLabelKey(tpl.kind_code))}
                        </Badge>
                        {!tpl.is_active && (
                          <Badge variant="secondary" className="shrink-0">
                            {t('docTemplatesSettings.inactive')}
                          </Badge>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Switch
                          checked={tpl.is_active}
                          onCheckedChange={() => handleToggleActive(tpl)}
                          aria-label={t('docTemplatesSettings.active')}
                        />
                        {t('docTemplatesSettings.active')}
                      </label>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        onClick={() => startEdit(tpl)}
                        title={t('common.edit')}
                        aria-label={t('common.edit')}
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            className="text-muted-foreground hover:text-destructive"
                            title={t('common.delete')}
                            aria-label={t('common.delete')}
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>{t('docTemplatesSettings.deleteTitle')}</AlertDialogTitle>
                            <AlertDialogDescription>
                              {t('docTemplatesSettings.deleteConfirm')}
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                            <AlertDialogAction
                              onClick={() => handleDelete(tpl)}
                              disabled={deleteMut.isPending}
                              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                            >
                              {t('common.delete')}
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Platform samples */}
      {samples.length > 0 && (
        <section className="space-y-3">
          <h4 className="text-base font-bold text-foreground">{t('docTemplatesSettings.samples')}</h4>
          <ul className="space-y-2" aria-label={t('docTemplatesSettings.samples')}>
            {samples.map((tpl) => (
              <li key={tpl.id}>
                <Card>
                  <CardContent className="flex flex-wrap items-center gap-3 p-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-foreground">{tpl.name}</span>
                        <Badge variant="outline" className="shrink-0">
                          {t(kindLabelKey(tpl.kind_code))}
                        </Badge>
                        <Badge variant="secondary" className="shrink-0">
                          {t('docTemplatesSettings.sampleBadge')}
                        </Badge>
                      </div>
                    </div>
                    <SampleTemplatePreviewDialog template={tpl} />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleCopy(tpl)}
                      disabled={copyMut.isPending}
                    >
                      <Copy className="size-3.5" />
                      {t('docTemplatesSettings.copyToMe')}
                    </Button>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

interface TemplateEditorProps {
  editor: EditorState;
  onChange: (next: EditorState) => void;
  onClose: () => void;
  onSave: () => void;
  onInsert: (code: string) => void;
  // Forwarded to the rich-text editor so placeholder chips can insert at the caret.
  richEditorRef: React.Ref<RichTextTemplateEditorHandle>;
  placeholderGroups: PlaceholderCatalogGroup[];
  preview: TemplatePreviewResult | undefined;
  isPreviewing: boolean;
  isSaving: boolean;
}

// Group headings + hints are UI text (Rule 5) — keyed on the backend group `key`, with the backend
// Russian label as the last-resort fallback.
const groupHeadingKey = (key: string) => `docTemplatesSettings.placeholderGroups.${key}`;
const groupHintKey = (key: string) => `docTemplatesSettings.placeholderGroupHints.${key}`;
const GROUPS_WITH_HINT = new Set(['company']);

function TemplateEditor({
  editor, onChange, onClose, onSave, onInsert, richEditorRef, placeholderGroups, preview, isPreviewing, isSaving,
}: TemplateEditorProps) {
  const { t } = useTranslation();

  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <div className="flex items-center justify-between">
          <h4 className="text-base font-bold text-foreground">
            {editor.id == null ? t('docTemplatesSettings.newTemplate') : t('docTemplatesSettings.editTemplate')}
          </h4>
          <Button variant="ghost" size="icon-xs" onClick={onClose} aria-label={t('common.cancel')}>
            <X className="size-4" />
          </Button>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="doc-tpl-name">{t('docTemplatesSettings.fields.name')}</Label>
            <Input
              id="doc-tpl-name"
              value={editor.name}
              onChange={(event) => onChange({ ...editor, name: event.target.value })}
              placeholder={t('docTemplatesSettings.fields.namePlaceholder')}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="doc-tpl-kind">{t('docTemplatesSettings.fields.kind')}</Label>
            <Select
              value={editor.kind}
              onValueChange={(value) => onChange({ ...editor, kind: value as KindCode })}
            >
              <SelectTrigger id="doc-tpl-kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {KIND_CODES.map((code) => (
                  <SelectItem key={code} value={code}>{t(kindLabelKey(code))}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Reinforces the T1 anti-duplication fix: requisites + signature come from the letterhead. */}
        <div className="flex items-start gap-2 rounded-md border border-info/40 bg-info/10 p-3 text-sm text-foreground">
          <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden="true" />
          <p>{t('docTemplatesSettings.letterheadHint')}</p>
        </div>

        <div className="grid gap-4 lg:grid-cols-[1fr_16rem]">
          <div className="space-y-1.5">
            <Label htmlFor="doc-tpl-body">{t('docTemplatesSettings.fields.body')}</Label>
            <RichTextTemplateEditor
              id="doc-tpl-body"
              ref={richEditorRef}
              value={editor.body_html}
              onChange={(html) => onChange({ ...editor, body_html: html })}
              templateKey={editor.id ?? 'new'}
            />
          </div>

          {/* Placeholder catalog — two groups (T1-c): dynamic data vs company requisites already in
              the letterhead шапка. Clicking a chip inserts {{code}} at the caret (Bitrix24 pattern). */}
          <div className="space-y-3">
            <Label>{t('docTemplatesSettings.placeholders')}</Label>
            <p className="text-xs text-muted-foreground">{t('docTemplatesSettings.placeholdersHint')}</p>
            {placeholderGroups.map((group) => (
              <div key={group.key} className="space-y-1.5">
                <p className="text-xs font-semibold text-foreground">
                  {t(groupHeadingKey(group.key), group.label)}
                </p>
                {GROUPS_WITH_HINT.has(group.key) && (
                  <p className="text-xs text-muted-foreground">{t(groupHintKey(group.key))}</p>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {group.items.map((entry) => (
                    <Button
                      key={entry.code}
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-auto py-1"
                      onClick={() => onInsert(entry.code)}
                      title={`{{${entry.code}}}`}
                    >
                      <span className="font-mono text-xs">{entry.label}</span>
                    </Button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Live preview — the FULL branded document (шапка + тело + подвал), so the author sees the
            requisites already print in the letterhead and stops duplicating them in the body (T1-a). */}
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <Label>{t('docTemplatesSettings.preview')}</Label>
            {isPreviewing && <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-hidden="true" />}
          </div>
          {preview && preview.document_html ? (
            <DocumentHtmlPreview html={preview.document_html} title={t('docTemplatesSettings.preview')} />
          ) : (
            <div className="rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm text-muted-foreground">{t('docTemplatesSettings.previewEmpty')}</p>
            </div>
          )}
          {preview && preview.warnings.length > 0 && (
            <p className="text-xs text-warning">
              {t('docTemplatesSettings.unknownPlaceholders', { list: preview.warnings.join(', ') })}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={isSaving}>
            {t('common.cancel')}
          </Button>
          <Button onClick={onSave} disabled={isSaving}>
            {isSaving ? <Loader2 className="size-4 animate-spin" /> : null}
            {t('common.save')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default DocumentTemplatesSettings;
