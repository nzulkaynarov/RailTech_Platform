import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { useBulkSubscriptionStatus } from '@/hooks/useAdmin';
import { useVerifyCompany } from '@/hooks/useAccounts';
import type { AdminQueueItem } from '@/api/adminApi';

/** Куда ведёт «Открыть» для каждого типа очереди. */
const QUEUE_TARGET: Record<string, string> = {
  kyc_pending: 'admin-kyc',
  role_application: 'admin-role-apps',
  subscription_past_due: 'admin-subscriptions',
  subscription_expiring: 'admin-subscriptions',
  invoice_overdue: 'admin-deals',
  support_urgent: 'admin-support',
  // Записи `supplier_bid_pending` здесь НЕТ: модель SupplierBid удалена (миграция crm/0015),
  // ни один сборщик триажа такой queue_type больше не отдаёт. Неизвестный тип падает
  // в 'admin-companies'.
};

/** Действие, ожидающее подтверждения оператором. */
export type PendingConfirm =
  | { kind: 'approve-kyc'; item: AdminQueueItem }
  | { kind: 'revoke-kyc'; item: AdminQueueItem }
  | { kind: 'activate-sub'; item: AdminQueueItem }
  | null;

/**
 * Действия над очередью триажа: куда вести по «Открыть» и что подтверждать перед мутацией.
 *
 * Rule 8 в его фронтовом прочтении: решение «что происходит по кнопке» живёт здесь, а панель
 * очереди остаётся отображением. Необратимые операции (подтверждение/отзыв KYC, активация
 * подписки) проходят через диалог — хук лишь копит намерение в `confirm`, а выполняет его
 * `runConfirm` после явного согласия.
 */
export function useQueueActions(onNavigate: (target: string) => void) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const verifyCompany = useVerifyCompany();
  const bulkSubStatus = useBulkSubscriptionStatus();
  const [confirm, setConfirm] = useState<PendingConfirm>(null);

  function refreshAll() {
    queryClient.invalidateQueries({ queryKey: ['admin-queue'] });
    queryClient.invalidateQueries({ queryKey: ['admin-pulse'] });
    queryClient.invalidateQueries({ queryKey: ['platform-dashboard'] });
  }

  function handleOpen(item: AdminQueueItem) {
    onNavigate(QUEUE_TARGET[item.queue_type] ?? 'admin-companies');
  }

  function handleApprove(item: AdminQueueItem) {
    if (item.queue_type === 'kyc_pending') {
      setConfirm({ kind: 'approve-kyc', item });
    } else if (item.queue_type === 'role_application') {
      onNavigate('admin-role-apps');
    } else if (item.queue_type === 'subscription_expiring' || item.queue_type === 'subscription_past_due') {
      setConfirm({ kind: 'activate-sub', item });
    }
  }

  function handleReject(item: AdminQueueItem) {
    if (item.queue_type === 'kyc_pending') {
      setConfirm({ kind: 'revoke-kyc', item });
    } else {
      handleOpen(item);
    }
  }

  async function runConfirm(payload: { reason: string }) {
    if (!confirm) return;
    if (confirm.kind === 'approve-kyc') {
      await verifyCompany.mutateAsync({
        companyId: confirm.item.entity_id,
        status_code: 'L2_VERIFIED',
        // Диалог собирал причину и ВЫБРАСЫВАЛ её здесь (соседняя ветка отзыва передавала).
        // Пока обоснование было необязательным, потеря была невидимой; с политикой
        // «без доказательств — только с обоснованием» этот путь упирался бы в отказ
        // сервера при заполненной форме.
        reason: payload.reason || undefined,
      });
      toast.success(t('adminQueue.kycApproved'));
      refreshAll();
      return;
    }
    if (confirm.kind === 'revoke-kyc') {
      await verifyCompany.mutateAsync({
        companyId: confirm.item.entity_id,
        status_code: 'L1_UNVERIFIED',
        reason: payload.reason,
      });
      toast.success(t('adminQueue.kycRevoked'));
      refreshAll();
      return;
    }
    if (confirm.kind === 'activate-sub') {
      await bulkSubStatus.mutateAsync({
        ids: [confirm.item.entity_id],
        status: 'ACTIVE',
      });
      toast.success(t('adminQueue.subscriptionActivated'));
      refreshAll();
      return;
    }
  }

  return { confirm, setConfirm, handleOpen, handleApprove, handleReject, runConfirm, refreshAll };
}
