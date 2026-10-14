import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ActionDialog } from '@/components/ActionDialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useDraftState } from '@/hooks/useDraftState';

const REASON_MAX = 2000;

/**
 * Отказ с причиной (отклонить КП, вернуть акт) — по образцу B2B `RejectQuoteDialog` / `RejectActDialog`:
 * причина обязательна (без основания отказ бесполезен обеим сторонам) и принадлежит открытию диалога
 * для конкретного объекта — брошенный текст не всплывает у другого КП/акта (`useDraftState`).
 */
export function ReasonDialog({
  target,
  open,
  onOpenChange,
  title,
  description,
  label,
  placeholder,
  confirmLabel,
  pending,
  error,
  onConfirm,
}: {
  /** Объект, к которому относится причина (id) — смена объекта сбрасывает черновик. */
  target: string | number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  label: string;
  placeholder: string;
  confirmLabel: string;
  pending: boolean;
  error?: unknown;
  onConfirm: (reason: string) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [reason, setReason] = useDraftState(`${open ? 'open' : 'closed'}:${target ?? ''}`, () => '');
  const [missing, setMissing] = useDraftState(open, () => false);
  const [touched, setTouched] = useState(false);

  const submit = () => {
    const text = reason.trim();
    if (!text) {
      setMissing(true);
      return;
    }
    onConfirm(text);
  };

  return (
    <ActionDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      confirmLabel={confirmLabel}
      confirmVariant="destructive"
      pending={pending}
      error={error}
      message={missing ? t('common.reasonRequired') : null}
      onSubmit={submit}
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor={id}>{label}</Label>
        <Textarea
          id={id}
          value={reason}
          maxLength={REASON_MAX}
          rows={4}
          required
          aria-invalid={(missing || touched) && !reason.trim() ? true : undefined}
          placeholder={placeholder}
          onBlur={() => setTouched(true)}
          onChange={(event) => {
            setReason(event.target.value);
            if (event.target.value.trim()) setMissing(false);
          }}
        />
      </div>
    </ActionDialog>
  );
}
