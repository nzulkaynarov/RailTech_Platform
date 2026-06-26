import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Mail, Eye, Send, Trash2, Plus } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Tabs, TabsList, TabsTrigger, TabsContent,
} from '@/components/ui/tabs';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';

import {
  useEmailTemplates, useCreateEmailTemplate, useUpdateEmailTemplate,
  useDeleteEmailTemplate, usePreviewEmailTemplate, useTestSendEmailTemplate,
} from '@/hooks/useAdmin';
import type {
  EmailTemplate, EmailTemplateDraft, EmailTemplatePreview,
} from '@/api/adminApi';
import { translateApiError } from '@/lib/apiError';
import { PageShell, ErrorState } from './shared/PageShell';

/** File template names a DB row may transparently override at send time. */
const TEMPLATE_KEYS = [
  'setup_password',
  'invite_member',
  'kyc_verified',
  'quote_sent',
  'reset_password',
  'role_application_approved',
  'role_application_rejected',
] as const;

const EMPTY_DRAFT: EmailTemplateDraft = {
  key: '',
  subject: '',
  html_body: '',
  text_body: '',
  available_variables: '',
  is_active: true,
};

/* ─── Preview dialog ────────────────────────────────────────────────── */

function PreviewDialog({
  preview, open, onOpenChange,
}: {
  preview: EmailTemplatePreview | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('admin.emailTemplates.preview.title')}</DialogTitle>
          <DialogDescription>{t('admin.emailTemplates.preview.description')}</DialogDescription>
        </DialogHeader>
        {preview ? (
          <div className="space-y-4">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">{t('admin.emailTemplates.fields.subject')}</Label>
              <p className="text-sm font-medium">{preview.subject}</p>
            </div>
            <Separator />
            <Tabs defaultValue={preview.html_body ? 'html' : 'text'}>
              <TabsList>
                <TabsTrigger value="html" disabled={!preview.html_body}>
                  {t('admin.emailTemplates.preview.html')}
                </TabsTrigger>
                <TabsTrigger value="text">{t('admin.emailTemplates.preview.text')}</TabsTrigger>
              </TabsList>
              <TabsContent value="html" className="mt-3">
                {preview.html_body ? (
                  <ScrollArea className="h-72 rounded-md border">
                    <iframe
                      title={t('admin.emailTemplates.preview.html')}
                      srcDoc={preview.html_body}
                      sandbox=""
                      className="h-72 w-full bg-background"
                    />
                  </ScrollArea>
                ) : (
                  <p className="text-sm text-muted-foreground">{t('admin.emailTemplates.preview.noHtml')}</p>
                )}
              </TabsContent>
              <TabsContent value="text" className="mt-3">
                <ScrollArea className="h-72 rounded-md border p-3">
                  <pre className="whitespace-pre-wrap text-sm">{preview.text_body}</pre>
                </ScrollArea>
              </TabsContent>
            </Tabs>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

/* ─── Test-send dialog ──────────────────────────────────────────────── */

function TestSendDialog({
  template, open, onOpenChange,
}: {
  template: EmailTemplate | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const testSend = useTestSendEmailTemplate();
  const [email, setEmail] = useState('');

  useEffect(() => {
    if (open) setEmail('');
  }, [open]);

  const submit = async () => {
    if (!template || !email.trim()) {
      toast.error(t('admin.emailTemplates.testSend.emailRequired'));
      return;
    }
    try {
      const res = await testSend.mutateAsync({ id: template.id, toEmail: email.trim() });
      if (res.status === 'SENT') {
        toast.success(t('admin.emailTemplates.testSend.sent', { email: res.to_email }));
        onOpenChange(false);
      } else {
        toast.error(t('admin.emailTemplates.testSend.failed'));
      }
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('admin.emailTemplates.testSend.title')}</DialogTitle>
          <DialogDescription>{t('admin.emailTemplates.testSend.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label>{t('admin.emailTemplates.testSend.toEmail')}</Label>
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@example.com"
          />
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={testSend.isPending}>
            <Send className="mr-2 h-4 w-4" />
            {t('admin.emailTemplates.testSend.send')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ─── Editor ────────────────────────────────────────────────────────── */

function Editor({
  template, isNew, onPreview, onTestSend, onDelete,
}: {
  template: EmailTemplate | null;
  isNew: boolean;
  onPreview: (preview: EmailTemplatePreview) => void;
  onTestSend: (template: EmailTemplate) => void;
  onDelete: (template: EmailTemplate) => void;
}) {
  const { t } = useTranslation();
  const createMut = useCreateEmailTemplate();
  const updateMut = useUpdateEmailTemplate();
  const previewMut = usePreviewEmailTemplate();

  const [draft, setDraft] = useState<EmailTemplateDraft>(EMPTY_DRAFT);

  useEffect(() => {
    if (template) {
      setDraft({
        key: template.key,
        subject: template.subject,
        html_body: template.html_body,
        text_body: template.text_body,
        available_variables: template.available_variables,
        is_active: template.is_active,
      });
    } else {
      setDraft(EMPTY_DRAFT);
    }
  }, [template]);

  const update = (patch: Partial<EmailTemplateDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const busy = createMut.isPending || updateMut.isPending;

  const save = async () => {
    if (!draft.key) {
      toast.error(t('admin.emailTemplates.keyRequired'));
      return;
    }
    try {
      if (isNew) {
        await createMut.mutateAsync(draft);
        toast.success(t('admin.emailTemplates.created'));
      } else if (template) {
        await updateMut.mutateAsync({ id: template.id, data: draft });
        toast.success(t('admin.emailTemplates.saved'));
      }
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const runPreview = async () => {
    if (!template) {
      toast.error(t('admin.emailTemplates.preview.saveFirst'));
      return;
    }
    try {
      const res = await previewMut.mutateAsync({ id: template.id });
      onPreview(res);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 space-y-2">
            <Label>{t('admin.emailTemplates.fields.key')}</Label>
            {isNew ? (
              <Select value={draft.key || undefined} onValueChange={(v) => update({ key: v })}>
                <SelectTrigger>
                  <SelectValue placeholder={t('admin.emailTemplates.fields.keyPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {TEMPLATE_KEYS.map((k) => (
                    <SelectItem key={k} value={k}>{k}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <p className="font-mono text-sm">{draft.key}</p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <Label className="text-xs text-muted-foreground">{t('admin.emailTemplates.fields.isActive')}</Label>
            <Switch checked={draft.is_active} onCheckedChange={(v) => update({ is_active: v })} />
          </div>
        </div>

        <div className="space-y-2">
          <Label>{t('admin.emailTemplates.fields.subject')}</Label>
          <Input value={draft.subject} onChange={(e) => update({ subject: e.target.value })} />
        </div>

        <div className="space-y-2">
          <Label>{t('admin.emailTemplates.fields.textBody')}</Label>
          <Textarea
            rows={8}
            className="font-mono text-sm"
            value={draft.text_body}
            onChange={(e) => update({ text_body: e.target.value })}
          />
        </div>

        <div className="space-y-2">
          <Label>{t('admin.emailTemplates.fields.htmlBody')}</Label>
          <p className="text-xs text-muted-foreground">{t('admin.emailTemplates.fields.htmlHint')}</p>
          <Textarea
            rows={10}
            className="font-mono text-sm"
            value={draft.html_body}
            onChange={(e) => update({ html_body: e.target.value })}
          />
        </div>

        <div className="space-y-2">
          <Label>{t('admin.emailTemplates.fields.availableVariables')}</Label>
          <Textarea
            rows={3}
            value={draft.available_variables}
            onChange={(e) => update({ available_variables: e.target.value })}
            placeholder={t('admin.emailTemplates.fields.variablesPlaceholder')}
          />
        </div>

        <Separator />

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            <Button onClick={save} disabled={busy}>
              {isNew ? t('admin.emailTemplates.create') : t('admin.emailTemplates.save')}
            </Button>
            {!isNew && template && (
              <>
                <Button variant="outline" onClick={runPreview} disabled={previewMut.isPending}>
                  <Eye className="mr-2 h-4 w-4" />
                  {t('admin.emailTemplates.previewAction')}
                </Button>
                <Button variant="outline" onClick={() => onTestSend(template)}>
                  <Send className="mr-2 h-4 w-4" />
                  {t('admin.emailTemplates.testSendAction')}
                </Button>
              </>
            )}
          </div>
          {!isNew && template && (
            <Button variant="ghost" className="text-destructive" onClick={() => onDelete(template)}>
              <Trash2 className="mr-2 h-4 w-4" />
              {t('admin.emailTemplates.delete')}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/* ─── Page ──────────────────────────────────────────────────────────── */

export function AdminEmailTemplatesPage() {
  const { t } = useTranslation();
  const { data: templates, isLoading, isError, refetch } = useEmailTemplates();
  const deleteMut = useDeleteEmailTemplate();

  const [selectedId, setSelectedId] = useState<number | 'new' | null>(null);
  const [preview, setPreview] = useState<EmailTemplatePreview | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [testSendTarget, setTestSendTarget] = useState<EmailTemplate | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<EmailTemplate | null>(null);

  const selectedTemplate = useMemo(() => {
    if (selectedId === null || selectedId === 'new') return null;
    return templates?.find((tpl) => tpl.id === selectedId) ?? null;
  }, [selectedId, templates]);

  const isNew = selectedId === 'new';

  const handlePreview = (res: EmailTemplatePreview) => {
    setPreview(res);
    setPreviewOpen(true);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      toast.success(t('admin.emailTemplates.deleted'));
      if (selectedId === deleteTarget.id) setSelectedId(null);
      setDeleteTarget(null);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const stats = [
    { label: t('admin.emailTemplates.stats.total'), value: String(templates?.length ?? 0) },
    {
      label: t('admin.emailTemplates.stats.active'),
      value: String(templates?.filter((tpl) => tpl.is_active).length ?? 0),
    },
  ];

  return (
    <PageShell
      title={t('admin.emailTemplates.title')}
      description={t('admin.emailTemplates.description')}
      icon={<Mail className="h-5 w-5" />}
      stats={stats}
    >
      {isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
          {/* List */}
          <div className="space-y-2">
            <Button
              variant={isNew ? 'default' : 'outline'}
              className="w-full justify-start"
              onClick={() => setSelectedId('new')}
            >
              <Plus className="mr-2 h-4 w-4" />
              {t('admin.emailTemplates.new')}
            </Button>
            {isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : (
              (templates ?? []).map((tpl) => (
                <button
                  key={tpl.id}
                  type="button"
                  onClick={() => setSelectedId(tpl.id)}
                  className={`flex w-full flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors hover:bg-muted/50 ${
                    selectedId === tpl.id ? 'border-primary ring-1 ring-primary' : ''
                  }`}
                >
                  <span className="font-mono text-sm font-medium">{tpl.key}</span>
                  <div className="flex items-center gap-2">
                    <Badge variant={tpl.is_active ? 'default' : 'outline'} className="text-xs">
                      {tpl.is_active
                        ? t('admin.emailTemplates.statusActive')
                        : t('admin.emailTemplates.statusInactive')}
                    </Badge>
                  </div>
                </button>
              ))
            )}
          </div>

          {/* Editor */}
          {selectedId === null ? (
            <Card>
              <CardContent className="flex h-64 flex-col items-center justify-center gap-2 text-center">
                <Mail className="h-6 w-6 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">{t('admin.emailTemplates.emptyEditor')}</p>
              </CardContent>
            </Card>
          ) : (
            <Editor
              key={isNew ? 'new' : selectedId}
              template={selectedTemplate}
              isNew={isNew}
              onPreview={handlePreview}
              onTestSend={(tpl) => setTestSendTarget(tpl)}
              onDelete={(tpl) => setDeleteTarget(tpl)}
            />
          )}
        </div>
      )}

      <PreviewDialog preview={preview} open={previewOpen} onOpenChange={setPreviewOpen} />

      <TestSendDialog
        template={testSendTarget}
        open={testSendTarget !== null}
        onOpenChange={(o) => !o && setTestSendTarget(null)}
      />

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('admin.emailTemplates.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('admin.emailTemplates.confirmDeleteDesc', { key: deleteTarget?.key })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('admin.emailTemplates.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} disabled={deleteMut.isPending}>
              {t('admin.emailTemplates.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default AdminEmailTemplatesPage;
