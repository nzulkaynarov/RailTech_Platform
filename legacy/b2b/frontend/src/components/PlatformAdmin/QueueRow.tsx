import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  ClipboardList,
  Clock,
  CreditCard,
  LifeBuoy,
  Receipt,
  ShieldCheck,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { AdminQueueItem, AdminQueueSeverity } from '@/api/adminApi';

const SEVERITY_TONE: Record<AdminQueueSeverity, string> = {
  critical: 'border-destructive/40 bg-destructive/5',
  warning: 'border-warning/40 bg-warning/5',
  info: 'border-info/40 bg-info/5',
};

const SEVERITY_BADGE: Record<AdminQueueSeverity, 'destructive' | 'secondary' | 'outline'> = {
  critical: 'destructive',
  warning: 'secondary',
  info: 'outline',
};

const QUEUE_ICON: Record<AdminQueueItem['queue_type'], React.ComponentType<{ className?: string }>> = {
  kyc_pending: ShieldCheck,
  role_application: ClipboardList,
  subscription_past_due: CreditCard,
  subscription_expiring: Clock,
  invoice_overdue: Receipt,
  support_urgent: LifeBuoy,
};

export interface QueueRowProps {
  item: AdminQueueItem;
  onOpen: (item: AdminQueueItem) => void;
  onApprove?: (item: AdminQueueItem) => void;
  onReject?: (item: AdminQueueItem) => void;
}

/**
 * Строка очереди триажа. Кнопки «Одобрить»/«Отклонить» показываются только тогда, когда
 * бэкенд заявил соответствующее действие в `item.actions` — набор действий приходит с
 * сервера, а не выводится из типа очереди на фронте.
 */
export function QueueRow({ item, onOpen, onApprove, onReject }: QueueRowProps) {
  const { t } = useTranslation();
  const Icon = QUEUE_ICON[item.queue_type] ?? AlertTriangle;
  return (
    <div
      className={cn(
        'flex items-start gap-3 border-l-2 px-3 py-2.5 transition-colors hover:bg-accent/50',
        SEVERITY_TONE[item.severity],
      )}
    >
      <div className="mt-0.5">
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-xs">
          <Badge variant={SEVERITY_BADGE[item.severity]} className="text-xs">
            {t(`adminQueue.severity.${item.severity}`)}
          </Badge>
          <span className="truncate font-medium">{item.title}</span>
          <span className="ml-auto text-muted-foreground">{item.age}</span>
        </div>
        {item.subtitle ? (
          <div className="mt-0.5 truncate text-xs text-muted-foreground">{item.subtitle}</div>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {onApprove && item.actions.some((a) => a.startsWith('approve')) ? (
          <Button
            size="sm"
            className="h-7 text-xs"
            onClick={(e) => {
              e.stopPropagation();
              onApprove(item);
            }}
          >
            {t('common.approve')}
          </Button>
        ) : null}
        {onReject && item.actions.some((a) => a.startsWith('reject') || a.startsWith('revoke')) ? (
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-xs"
            onClick={(e) => {
              e.stopPropagation();
              onReject(item);
            }}
          >
            {t('common.reject')}
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          onClick={(e) => {
            e.stopPropagation();
            onOpen(item);
          }}
        >
          {t('common.open')}
        </Button>
      </div>
    </div>
  );
}
