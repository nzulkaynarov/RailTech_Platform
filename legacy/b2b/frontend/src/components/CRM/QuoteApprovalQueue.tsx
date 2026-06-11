import React from 'react';
import { useTranslation } from 'react-i18next';
import { ClipboardCheck, ChevronRight } from 'lucide-react';
import { useMyApprovalQueue } from '@/hooks/useCRM';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/ui/StatusBadge';

interface QuoteApprovalQueueProps {
  /** Navigate to the deals surface so the reviewer can open the КП. */
  onNavigate: (page: string) => void;
}

/** Map a КП chain status to a StatusBadge variant. */
const STATUS_VARIANT: Record<string, 'warning' | 'info' | 'success'> = {
  DRAFT: 'info',
  PENDING_TRADE_REVIEW: 'warning',
  PENDING_APPROVAL: 'warning',
  READY_TO_SEND: 'success',
};

/**
 * "My approval queue" — КП waiting on the current member's workspace-role step,
 * scoped server-side to their own companies (see crm.services.quotes.approval_queue_for).
 * Renders nothing when the queue is empty so it stays out of the way for members
 * with no approval duties.
 */
export const QuoteApprovalQueue: React.FC<QuoteApprovalQueueProps> = ({ onNavigate }) => {
  const { t } = useTranslation();
  const { data: queue = [], isLoading } = useMyApprovalQueue();

  if (isLoading || queue.length === 0) return null;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-2 py-3">
        <ClipboardCheck className="h-4 w-4 text-muted-foreground" />
        <CardTitle className="text-sm font-semibold">
          {t('quote.approvalChain.queueTitle')}
        </CardTitle>
        <StatusBadge label={String(queue.length)} variant="warning" className="ml-1" />
      </CardHeader>
      <CardContent className="flex flex-col gap-2 pt-0">
        {queue.map((quote) => (
          <button
            key={quote.id}
            type="button"
            onClick={() => onNavigate('crm-deals')}
            className="flex items-center justify-between rounded-md border px-3 py-2 text-left transition-colors hover:bg-muted/50"
          >
            <div className="flex flex-col leading-tight">
              <span className="text-sm font-semibold">
                {t('quote.approvalChain.queueDeal', { id: quote.deal })}
              </span>
              <span className="text-xs text-muted-foreground">
                {t('quote.approvalChain.queueVersion', { version: quote.version })}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <StatusBadge
                label={quote.status_name || quote.status_code}
                variant={STATUS_VARIANT[quote.status_code] ?? 'neutral'}
              />
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            </div>
          </button>
        ))}
      </CardContent>
    </Card>
  );
};
