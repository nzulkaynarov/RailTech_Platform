import type { FormEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2 } from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

/**
 * Диалог действия клиента (принять КП, подписать договор, вернуть акт…): форма с подтверждением.
 * Диалог не закрывается на ошибке — ответ ERP (409 «уже принято», «код неверен», 403…) показан
 * внутри него текстом из `apiErrors.*`, чтобы человек понял, что произошло, и мог исправить ввод.
 */
export function ActionDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  confirmVariant = 'default',
  pending,
  error,
  message,
  onSubmit,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  confirmVariant?: 'default' | 'destructive';
  pending: boolean;
  /** Ошибка последней попытки (ответ ERP) — показывается текстом внутри диалога. */
  error?: unknown;
  /** Своё сообщение вместо ответа ERP (проверка формы до отправки). */
  message?: string | null;
  onSubmit: () => void;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!pending) onSubmit();
  };
  const problem = message || (error ? t(apiErrorKey(error)) : null);
  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          {children}
          {problem ? (
            <Alert variant="destructive">
              <AlertTriangle aria-hidden="true" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          ) : null}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline" disabled={pending}>
                {t('common.cancel')}
              </Button>
            </DialogClose>
            <Button type="submit" variant={confirmVariant} disabled={pending}>
              {pending ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
              {confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
