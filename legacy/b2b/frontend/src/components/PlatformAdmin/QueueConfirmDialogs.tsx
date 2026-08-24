import { useTranslation } from 'react-i18next';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { translateApiError } from '@/lib/apiError';
import { EVIDENCE_GAP_LABEL, type EvidenceGap } from '@/pages/admin-kyc/evidence';
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
 *
 * Очередь — ПЯТЫЙ путь выдачи уровня, и правила у него те же, что у реестра KYC: компания
 * без загруженных документов или без ИНН подтверждается только с обоснованием (политика
 * владельца 2026-06-03). Пробелы считает сервер и присылает кодами в строке очереди —
 * своего предиката у витрины нет, иначе их стало бы три.
 */
export function QueueConfirmDialogs({ confirm, onClose, onConfirm }: QueueConfirmDialogsProps) {
  const { t } = useTranslation();
  const close = (open: boolean) => {
    if (!open) onClose();
  };
  const gaps = (confirm?.item.evidence_gaps ?? []) as EvidenceGap[];
  const missingEvidence = confirm?.kind === 'approve-kyc' && gaps.length > 0;
  const gapNames = gaps.map((gap) => t(EVIDENCE_GAP_LABEL[gap] ?? gap)).join(', ');

  return (
    <>
      <ConfirmActionDialog
        open={confirm?.kind === 'approve-kyc'}
        onOpenChange={close}
        title={t('adminQueue.confirm.kycApproveTitle')}
        description={
          missingEvidence ? (
            <>
              {t('adminQueue.confirm.kycApproveDescription', { name: confirm?.item.title ?? '' })}
              <span className="mt-2 block font-medium text-warning">
                {t('kycManager.approveWithoutEvidence', { gaps: gapNames })}
              </span>
            </>
          ) : (
            t('adminQueue.confirm.kycApproveDescription', { name: confirm?.item.title ?? '' })
          )
        }
        variant={missingEvidence ? 'warning' : 'primary'}
        confirmLabel={t('common.approve')}
        showReason
        requireReason={missingEvidence}
        reasonLabel={
          missingEvidence ? t('kycManager.approveReasonRequired') : t('adminQueue.confirm.commentOptional')
        }
        diff={
          confirm?.kind === 'approve-kyc'
            ? [{ label: t('confirmDialog.kycLevel'), before: 'PROFILE_SUBMITTED', after: 'L2_VERIFIED' }]
            : undefined
        }
        translateError={(code) => translateApiError(code)}
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
        translateError={(code) => translateApiError(code)}
        onConfirm={onConfirm}
      />
      <ConfirmActionDialog
        open={confirm?.kind === 'activate-sub'}
        onOpenChange={close}
        title={t('adminQueue.confirm.subActivateTitle')}
        description={confirm?.item.title ?? ''}
        variant="primary"
        confirmLabel={t('common.activate')}
        translateError={(code) => translateApiError(code)}
        onConfirm={onConfirm}
      />
    </>
  );
}
