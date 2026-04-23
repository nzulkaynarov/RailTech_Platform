import { FormEvent, ReactNode, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface ConfirmActionDiff {
  label: string;
  before?: string;
  after?: string;
}

export type ConfirmActionVariant = 'default' | 'primary' | 'destructive' | 'warning';

export interface ConfirmActionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  diff?: ConfirmActionDiff[];
  variant?: ConfirmActionVariant;
  confirmLabel?: string;
  cancelLabel?: string;
  /** When true, the reason textarea must be non-empty before Confirm is enabled. */
  requireReason?: boolean;
  /** When true, shows a reason textarea (optional or required per `requireReason`). */
  showReason?: boolean;
  /** Pre-canned reason templates available from a dropdown. */
  reasonTemplates?: string[];
  reasonLabel?: string;
  /** When set, the user must type this string exactly to enable Confirm. */
  typeToConfirm?: string;
  /** Extra fields under the reason textarea (e.g. target-level selector). */
  extraFields?: ReactNode;
  /** Called after the user confirms. Return value is ignored; thrown errors surface via toast. */
  onConfirm: (payload: { reason: string }) => Promise<unknown> | unknown;
  /** Error-translation function: maps backend error code → user-facing string. */
  translateError?: (code: string) => string | null;
}

export function ConfirmActionDialog(props: ConfirmActionDialogProps): React.ReactNode {
  const { t } = useTranslation();
  const {
    open,
    onOpenChange,
    title,
    description,
    diff,
    variant = 'default',
    confirmLabel,
    cancelLabel,
    requireReason = false,
    showReason = false,
    reasonTemplates,
    reasonLabel,
    typeToConfirm,
    extraFields,
    onConfirm,
    translateError,
  } = props;

  const [reason, setReason] = useState('');
  const [typed, setTyped] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      setReason('');
      setTyped('');
      setSubmitting(false);
    }
  }, [open]);

  const reasonOk = !requireReason || reason.trim().length > 0;
  const typedOk = !typeToConfirm || typed.trim() === typeToConfirm.trim();
  const canConfirm = reasonOk && typedOk && !submitting;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canConfirm) return;
    setSubmitting(true);
    try {
      await onConfirm({ reason: reason.trim() });
      onOpenChange(false);
    } catch (err: unknown) {
      type AxiosLike = { response?: { data?: { detail?: string; error?: string } } };
      const detail =
        (err as AxiosLike)?.response?.data?.detail ||
        (err as AxiosLike)?.response?.data?.error ||
        '';
      const message =
        (detail && translateError?.(String(detail))) ||
        (detail ? String(detail) : (err instanceof Error ? err.message : t('common.error')));
      toast.error(message);
      setSubmitting(false);
    }
  }

  const confirmVariant =
    variant === 'destructive'
      ? 'destructive'
      : variant === 'warning'
        ? 'secondary'
        : 'default';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description ? (
              <DialogDescription>{description}</DialogDescription>
            ) : null}
          </DialogHeader>

          {diff && diff.length > 0 ? (
            <ul className="mt-3 space-y-1 rounded-md border bg-muted/30 p-3 text-xs">
              {diff.map((d) => (
                <li key={d.label} className="flex items-start justify-between gap-2">
                  <span className="text-muted-foreground">{d.label}</span>
                  <span className="font-medium text-right">
                    {d.before ? (
                      <>
                        <span className="text-muted-foreground line-through">{d.before}</span>
                        {' → '}
                      </>
                    ) : null}
                    <span className={cn(variant === 'destructive' && 'text-destructive')}>
                      {d.after ?? '—'}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : null}

          {extraFields ? <div className="mt-3">{extraFields}</div> : null}

          {showReason || requireReason ? (
            <div className="mt-3 space-y-2">
              <Label htmlFor="confirm-reason" className="text-xs">
                {reasonLabel ?? t('confirmDialog.reason')}
                {requireReason ? <span className="ml-1 text-destructive">*</span> : null}
              </Label>
              {reasonTemplates && reasonTemplates.length > 0 ? (
                <Select onValueChange={(v) => setReason(v)} value={undefined}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder={t('confirmDialog.templates')} />
                  </SelectTrigger>
                  <SelectContent>
                    {reasonTemplates.map((tpl) => (
                      <SelectItem key={tpl} value={tpl} className="text-xs">
                        {tpl}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}
              <Textarea
                id="confirm-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={t('confirmDialog.reasonPlaceholder')}
                rows={3}
                className="text-xs"
                maxLength={5000}
              />
            </div>
          ) : null}

          {typeToConfirm ? (
            <div className="mt-3 space-y-2">
              <Label htmlFor="confirm-typed" className="text-xs">
                {t('confirmDialog.typeToConfirm', { value: typeToConfirm })}
              </Label>
              <Input
                id="confirm-typed"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={typeToConfirm}
                className="h-8 text-xs"
              />
            </div>
          ) : null}

          <DialogFooter className="mt-4 gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              {cancelLabel ?? t('common.cancel')}
            </Button>
            <Button
              type="submit"
              variant={confirmVariant}
              disabled={!canConfirm}
            >
              {submitting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : null}
              {confirmLabel ?? t('common.confirm')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
