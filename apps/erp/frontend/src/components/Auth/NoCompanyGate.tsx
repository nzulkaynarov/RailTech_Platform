import { useQuery } from '@tanstack/react-query';
import { setupApi } from '@/api/setupApi';
import { LoadingSkeleton } from '@/components/LoadingSkeleton';
import { NoCompanyScreen } from './NoCompanyScreen';
import { OwnCompanySetupScreen } from './OwnCompanySetupScreen';

/**
 * Вошёл, но компании нет (FIX-65): администратор при `can_setup` проходит мастер своей компании,
 * сотрудник видит экран «не привязана» — с пояснением, что настройка ERP ещё не завершена.
 * Статус недоступен (сеть) — обычный экран без пояснения: не показываем мастер наугад.
 */
export function NoCompanyGate() {
  const { data, isLoading } = useQuery({ queryKey: ['setup-status'], queryFn: setupApi.getStatus, retry: false });
  if (isLoading) return <LoadingSkeleton />;
  if (data?.can_setup) return <OwnCompanySetupScreen />;
  return <NoCompanyScreen setupPending={data?.setup_required === true} />;
}
