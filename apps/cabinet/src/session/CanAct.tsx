import type { ReactNode } from 'react';

import { useCanAct } from './useMe';

/** Показывает действие только контакту с правом действовать; остальным — `fallback` (по умолчанию ничего). */
export function CanAct({ children, fallback = null }: { children: ReactNode; fallback?: ReactNode }) {
  return useCanAct() ? <>{children}</> : <>{fallback}</>;
}
