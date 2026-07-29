import { useTranslation } from 'react-i18next';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import type { PendingConfirm } from './useQueueActions';

export interface QueueConfirmDialogsProps {
  confirm: PendingConfirm;
  onClose: () => void;
  onConfirm: (payload: { reason: string }) => Promise<void>;
}

/**
 * Диалоги подтверждения для необратимых операций очереди триажа.
 *
 * Отзыв KYC требует причины (`requireReason`) — она уходит в аудит; подтверждение KYC
 * показывает diff уровня, чтобы оператор видел, что именно меняется.
 */
export function QueueConfirmDialogs({ confirm, onClose, onConfirm }: QueueConfirmDialogsProps) {
  const { t } = useTranslation();
  const close = (open: boolean) => {
    if (!open) onClose();
  };

  return (
    <>
      <ConfirmActionDialog
        open={confirm?.kind === 'approve-kyc'}
        onOpenChange={close}
        title={t('adminQueue.confirm.kycApproveTitle')}
        description={t('adminQueue.confirm.kycApproveDescription', { name: confirm?.item.title ?? '' })}
        variant="primary"
        confirmLabel={t('common.approve')}
        showReason
        reasonLabel={t('adminQueue.confirm.commentOptional')}
        diff={
          confirm?.kind === 'approve-kyc'
            ? [{ label: t('confirmDialog.kycLevel'), before: 'PROFILE_SUBMITTED', after: 'L2_VERIFIED' }]
            : undefined
        }
        onConfirm={onConfirm}
      />
      <ConfirmActionDialog
        open={confirm?.kind === 'revoke-kyc'}
        onOpenChange={close}
        title={t('adminQueue.confirm.kycRevokeTitle')}
        description={t('adminQueue.confirm.kycRevokeDescription', { name: confirm?.item.title ?? '' })}
        variant="destructive"
        confirmLabel={t('common.revoke')}
        requireReason
        reasonTemplates={[
          t('adminQueue.reasonTemplates.docsInvalid'),
          t('adminQueue.reasonTemplates.innMismatch'),
          t('adminQueue.reasonTemplates.other'),
        ]}
        onConfirm={onConfirm}
      />
      <ConfirmActionDialog
        open={confirm?.kind === 'activate-sub'}
        onOpenChange={close}
        title={t('adminQueue.confirm.subActivateTitle')}
        description={confirm?.item.title ?? ''}
        variant="primary"
        confirmLabel={t('common.activate')}
        onConfirm={onConfirm}
      />
    </>
  );
}
