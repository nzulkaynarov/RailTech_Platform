import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { useQueueActions } from '../useQueueActions';
import type { AdminQueueItem } from '@/api/adminApi';
import { createTestI18n, createTestQueryClient } from '@/test/renderWithProviders';
import { I18nextProvider } from 'react-i18next';

// Слой действий очереди триажа подтверждает и ОТЗЫВАЕТ KYC — необратимые операции.
// До рефактора эта логика жила внутри 692-строчной страницы и не была покрыта ничем.
// Здесь фиксируется главное: (1) «Открыть» ведёт в правильный раздел, (2) необратимое
// действие не выполняется сразу, а копится в `confirm` до явного согласия оператора,
// (3) отзыв KYC уходит с причиной.

const verifyCompany = vi.fn();
const bulkSubStatus = vi.fn();

vi.mock('@/hooks/useAccounts', () => ({
  useVerifyCompany: () => ({ mutateAsync: verifyCompany }),
}));
vi.mock('@/hooks/useAdmin', () => ({
  useBulkSubscriptionStatus: () => ({ mutateAsync: bulkSubStatus }),
}));

function item(queue_type: string, entity_id = 42): AdminQueueItem {
  return {
    queue_type,
    entity_id,
    title: 'ООО «Тест»',
    subtitle: '',
    severity: 'warning',
    age: '1 дн.',
    actions: [],
  } as unknown as AdminQueueItem;
}

let queryClient: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>
    <I18nextProvider i18n={createTestI18n()}>{children}</I18nextProvider>
  </QueryClientProvider>
);

beforeEach(() => {
  queryClient = createTestQueryClient();
  verifyCompany.mockReset().mockResolvedValue({});
  bulkSubStatus.mockReset().mockResolvedValue({});
});

describe('useQueueActions — «Открыть» ведёт в свой раздел', () => {
  it.each([
    ['kyc_pending', 'admin-kyc'],
    ['role_application', 'admin-role-apps'],
    ['subscription_past_due', 'admin-subscriptions'],
    ['subscription_expiring', 'admin-subscriptions'],
    ['invoice_overdue', 'admin-deals'],
    ['support_urgent', 'admin-support'],
  ])('%s → %s', (queueType, target) => {
    const onNavigate = vi.fn();
    const { result } = renderHook(() => useQueueActions(onNavigate), { wrapper });
    act(() => result.current.handleOpen(item(queueType)));
    expect(onNavigate).toHaveBeenCalledWith(target);
  });

  it('неизвестный тип падает в admin-companies, а не в никуда', () => {
    const onNavigate = vi.fn();
    const { result } = renderHook(() => useQueueActions(onNavigate), { wrapper });
    act(() => result.current.handleOpen(item('supplier_bid_pending')));
    expect(onNavigate).toHaveBeenCalledWith('admin-companies');
  });
});

describe('useQueueActions — необратимое требует подтверждения', () => {
  it('одобрение KYC не мутирует сразу, а поднимает диалог', () => {
    const { result } = renderHook(() => useQueueActions(vi.fn()), { wrapper });
    act(() => result.current.handleApprove(item('kyc_pending')));
    expect(result.current.confirm?.kind).toBe('approve-kyc');
    expect(verifyCompany).not.toHaveBeenCalled();
  });

  it('отклонение KYC поднимает диалог отзыва', () => {
    const { result } = renderHook(() => useQueueActions(vi.fn()), { wrapper });
    act(() => result.current.handleReject(item('kyc_pending')));
    expect(result.current.confirm?.kind).toBe('revoke-kyc');
  });

  it('заявка на роль не подтверждается здесь, а уводит в свой раздел', () => {
    const onNavigate = vi.fn();
    const { result } = renderHook(() => useQueueActions(onNavigate), { wrapper });
    act(() => result.current.handleApprove(item('role_application')));
    expect(result.current.confirm).toBeNull();
    expect(onNavigate).toHaveBeenCalledWith('admin-role-apps');
  });

  it('отклонение НЕ-KYC записи просто открывает её', () => {
    const onNavigate = vi.fn();
    const { result } = renderHook(() => useQueueActions(onNavigate), { wrapper });
    act(() => result.current.handleReject(item('invoice_overdue')));
    expect(result.current.confirm).toBeNull();
    expect(onNavigate).toHaveBeenCalledWith('admin-deals');
  });
});

describe('useQueueActions — runConfirm выполняет подтверждённое', () => {
  it('одобрение KYC ставит L2_VERIFIED', async () => {
    const { result } = renderHook(() => useQueueActions(vi.fn()), { wrapper });
    act(() => result.current.handleApprove(item('kyc_pending', 7)));
    await act(async () => {
      await result.current.runConfirm({ reason: '' });
    });
    expect(verifyCompany).toHaveBeenCalledWith({ companyId: 7, status_code: 'L2_VERIFIED' });
  });

  it('отзыв KYC уходит с причиной — она попадает в аудит', async () => {
    const { result } = renderHook(() => useQueueActions(vi.fn()), { wrapper });
    act(() => result.current.handleReject(item('kyc_pending', 9)));
    await act(async () => {
      await result.current.runConfirm({ reason: 'Документы не читаются' });
    });
    expect(verifyCompany).toHaveBeenCalledWith({
      companyId: 9,
      status_code: 'L1_UNVERIFIED',
      reason: 'Документы не читаются',
    });
  });

  it('активация подписки шлёт ACTIVE по одному id', async () => {
    const { result } = renderHook(() => useQueueActions(vi.fn()), { wrapper });
    act(() => result.current.handleApprove(item('subscription_past_due', 3)));
    await act(async () => {
      await result.current.runConfirm({ reason: '' });
    });
    expect(bulkSubStatus).toHaveBeenCalledWith({ ids: [3], status: 'ACTIVE' });
  });

  it('без поднятого диалога runConfirm ничего не делает', async () => {
    const { result } = renderHook(() => useQueueActions(vi.fn()), { wrapper });
    await act(async () => {
      await result.current.runConfirm({ reason: 'что-то' });
    });
    expect(verifyCompany).not.toHaveBeenCalled();
    expect(bulkSubStatus).not.toHaveBeenCalled();
  });

  it('после мутации инвалидируются все три источника дашборда', async () => {
    const spy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useQueueActions(vi.fn()), { wrapper });
    act(() => result.current.handleApprove(item('kyc_pending')));
    await act(async () => {
      await result.current.runConfirm({ reason: '' });
    });
    await waitFor(() => {
      const keys = spy.mock.calls.map((c) => (c[0] as { queryKey: string[] }).queryKey[0]);
      expect(keys).toEqual(expect.arrayContaining(['admin-queue', 'admin-pulse', 'platform-dashboard']));
    });
  });
});
