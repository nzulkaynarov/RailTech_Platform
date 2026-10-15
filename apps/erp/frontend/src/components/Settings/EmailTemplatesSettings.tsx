import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Mail, Eye, Send, Trash2, Plus, Loader2 } from 'lucide-react';

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

import { useDraftState } from '@/hooks/useDraftState';
import {
  useEmailTemplates,
  useCreateEmailTemplate,
  useUpdateEmailTemplate,
  useDeleteEmailTemplate,
  usePreviewEmailTemplate,
  useTestSendEmailTemplate,
} from '@/hooks/useEmailTemplates';
import type {
  EmailTemplate,
  EmailTemplateDraft,
  EmailTemplatePreview,
} from '@/api/emailTemplatesApi';
import { translateApiError } from '@/lib/apiError';

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

function PreviewDialog({
  preview,
  open,
  onOpenChange,
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
          <DialogTitle>{t('settings.emailTemplates.previewTitle')}</DialogTitle>
          <DialogDescription>{t('settings.emailTemplates.previewDesc')}</DialogDescription>
        </DialogHeader>
        {preview ? (
          <div className="space-y-4">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">{t('settings.emailTemplates.subject')}</Label>
              <p className="text-sm font-medium">{preview.subject}</p>
            </div>
            <Separator />
            <Tabs defaultValue={preview.html_body ? 'html' : 'text'}>
              <TabsList>
                <TabsTrigger value="html" disabled={!preview.html_body}>
                  {t('settings.emailTemplates.htmlTab')}
                </TabsTrigger>
                <TabsTrigger value="text">{t('settings.emailTemplates.textTab')}</TabsTrigger>
              </TabsList>
              <TabsContent value="html" className="mt-3">
                {preview.html_body ? (
                  <ScrollArea className="h-72 rounded-md border">
                    <iframe
                      title={t('settings.emailTemplates.htmlTab')}
                      srcDoc={preview.html_body}
                      sandbox=""
                      className="h-72 w-full bg-background"
                    />
                  </ScrollArea>
                ) : (
                  <p className="text-sm text-muted-foreground">{t('settings.emailTemplates.noHtml')}</p>
                )}
              </TabsContent>
              <TabsContent value="text" className="mt-3">
                <ScrollArea className="h-72 rounded-md border p-3">
                  <pre className="whitespace-pre-wrap font-mono text-sm">{preview.text_body}</pre>
                </ScrollArea>
              </TabsContent>
            </Tabs>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function TestSendDialog({
  template,
  open,
  onOpenChange,
}: {
  template: EmailTemplate | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const testSend = useTestSendEmailTemplate();
  const [email, setEmail] = useDraftState(open, () => '');

  const submit = async () => {
    if (!template || !email.trim()) {
      toast.error(t('settings.emailTemplates.emailRequired'));
      return;
    }
    try {
      const res = await testSend.mutateAsync({ id: template.id, toEmail: email.trim() });
      if (res.status === 'SENT') {
        toast.success(t('settings.emailTemplates.sentSuccess', { email: res.to_email }));
        onOpenChange(false);
      } else {
        toast.error(t('settings.emailTemplates.sentFailed'));
      }
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('settings.emailTemplates.testSendTitle')}</DialogTitle>
          <DialogDescription>{t('settings.emailTemplates.testSendDesc')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="test-send-email">{t('settings.emailTemplates.toEmail')}</Label>
          <Input
            id="test-send-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@example.com"
          />
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={testSend.isPending}>
            {testSend.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-2 h-4 w-4" />
            )}
            {t('settings.emailTemplates.send')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Editor({
  template,
  isNew,
  onPreview,
  onTestSend,
  onDelete,
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

  const [draft, setDraft] = useDraftState<typeof template, EmailTemplateDraft>(template, (source) =>
    source
      ? {
          key: source.key,
          subject: source.subject,
          html_body: source.html_body,
          text_body: source.text_body,
          available_variables: source.available_variables,
          is_active: source.is_active,
        }
      : EMPTY_DRAFT,
  );

  const update = (patch: Partial<EmailTemplateDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const busy = createMut.isPending || updateMut.isPending;

  const save = async () => {
    if (!draft.key) {
      toast.error(t('settings.emailTemplates.keyRequired'));
      return;
    }
    if (!draft.subject.trim()) {
      toast.error(t('settings.emailTemplates.subjectRequired'));
      return;
    }
    if (!draft.text_body.trim()) {
      toast.error(t('settings.emailTemplates.textBodyRequired'));
      return;
    }
    try {
      if (isNew) {
        await createMut.mutateAsync(draft);
        toast.success(t('settings.emailTemplates.created'));
      } else if (template) {
        await updateMut.mutateAsync({ id: template.id, data: draft });
        toast.success(t('settings.emailTemplates.saved'));
      }
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const runPreview = async () => {
    if (!template) {
      toast.error(t('settings.emailTemplates.saveFirstForPreview'));
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
            <Label htmlFor="template-key">{t('settings.emailTemplates.key')}</Label>
            {isNew ? (
              <Select value={draft.key || undefined} onValueChange={(v) => update({ key: v })}>
                <SelectTrigger id="template-key">
                  <SelectValue placeholder={t('settings.emailTemplates.keyPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {TEMPLATE_KEYS.map((k) => (
                    <SelectItem key={k} value={k}>{k}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <p className="font-mono text-sm font-semibold">{draft.key}</p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <Label className="text-xs text-muted-foreground">{t('settings.emailTemplates.isActive')}</Label>
            <Switch checked={draft.is_active} onCheckedChange={(v) => update({ is_active: v })} />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="template-subject">{t('settings.emailTemplates.subject')}</Label>
          <Input
            id="template-subject"
            value={draft.subject}
            onChange={(e) => update({ subject: e.target.value })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="template-text-body">{t('settings.emailTemplates.textBody')}</Label>
          <Textarea
            id="template-text-body"
            rows={6}
            className="font-mono text-sm"
            value={draft.text_body}
            onChange={(e) => update({ text_body: e.target.value })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="template-html-body">{t('settings.emailTemplates.htmlBody')}</Label>
          <p className="text-xs text-muted-foreground">{t('settings.emailTemplates.htmlHint')}</p>
          <Textarea
            id="template-html-body"
            rows={8}
            className="font-mono text-sm"
            value={draft.html_body}
            onChange={(e) => update({ html_body: e.target.value })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="template-variables">{t('settings.emailTemplates.availableVariables')}</Label>
          <Textarea
            id="template-variables"
            rows={2}
            value={draft.available_variables}
            onChange={(e) => update({ available_variables: e.target.value })}
            placeholder={t('settings.emailTemplates.variablesPlaceholder')}
          />
        </div>

        <Separator />

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            <Button onClick={save} disabled={busy}>
              {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isNew ? t('settings.emailTemplates.create') : t('common.save')}
            </Button>
            {!isNew && template && (
              <>
                <Button variant="outline" onClick={runPreview} disabled={previewMut.isPending}>
                  <Eye className="mr-2 h-4 w-4" />
                  {t('settings.emailTemplates.previewAction')}
                </Button>
                <Button variant="outline" onClick={() => onTestSend(template)}>
                  <Send className="mr-2 h-4 w-4" />
                  {t('settings.emailTemplates.testSendAction')}
                </Button>
              </>
            )}
          </div>
          {!isNew && template && (
            <Button variant="ghost" className="text-destructive hover:bg-destructive/10" onClick={() => onDelete(template)}>
              <Trash2 className="mr-2 h-4 w-4" />
              {t('common.delete')}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function EmailTemplatesSettings() {
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
      toast.success(t('settings.emailTemplates.deleted'));
      if (selectedId === deleteTarget.id) setSelectedId(null);
      setDeleteTarget(null);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <Mail className="h-5 w-5 text-primary" />
          {t('settings.emailTemplates.title')}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">{t('settings.emailTemplates.subtitle')}</p>
      </div>

      {isError ? (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
          <p className="text-sm text-destructive">{t('common.loadError')}</p>
          <Button variant="outline" className="mt-3" onClick={() => refetch()}>
            {t('common.retry')}
          </Button>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
          <div className="space-y-2">
            <Button
              variant={isNew ? 'default' : 'outline'}
              className="w-full justify-start"
              onClick={() => setSelectedId('new')}
            >
              <Plus className="mr-2 h-4 w-4" />
              {t('settings.emailTemplates.new')}
            </Button>
            {isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {(templates ?? []).map((tpl) => (
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
                          ? t('settings.emailTemplates.statusActive')
                          : t('settings.emailTemplates.statusInactive')}
                      </Badge>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div>
            {selectedId === null ? (
              <Card>
                <CardContent className="flex h-64 flex-col items-center justify-center gap-2 text-center">
                  <Mail className="h-6 w-6 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">{t('settings.emailTemplates.emptyEditor')}</p>
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
            <AlertDialogTitle>{t('settings.emailTemplates.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings.emailTemplates.confirmDeleteDesc', { key: deleteTarget?.key })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} disabled={deleteMut.isPending}>
              {t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default EmailTemplatesSettings;
