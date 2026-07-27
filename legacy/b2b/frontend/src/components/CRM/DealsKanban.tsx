import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Handshake, UserCheck, Loader2, Clock } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatWaiting, isUnclaimedRfq, waitingHours } from '@/lib/waiting';
import { useClaimDeal } from '@/hooks/useCRM';
import { useIsSoloSeller } from '@/hooks/useCapabilities';
import { DEAL_STAGE_LABEL_KEY } from '@/lib/codes';
import { translateApiError } from '@/lib/apiError';
import type { Deal } from '@/api/crmApi';

interface DealStage {
  code: string;
  name: string;
}
import { useCurrencyStore } from '@/store/currencyStore';
import { sumMoney } from '@/utils/decimal';

interface DealsKanbanProps {
  deals: Deal[];
  stages: DealStage[] | undefined;
  onOpen?: (deal: Deal) => void;
}

/**
 * Read-only kanban view of deals grouped by FSM stage. Columns follow the
 * stage order from the backend (`sort_order`), so stage changes in master
 * data are reflected automatically. No drag-and-drop — stage transitions
 * remain controlled via the Deal detail / FSM actions to preserve the audit
 * trail. Clicking a card opens the same detail sheet as the list view.
 */
export function DealsKanban({ deals, stages, onOpen }: DealsKanbanProps) {
  const { t } = useTranslation();
  const format = useCurrencyStore((s) => s.format);
  const claimMut = useClaimDeal();
  // Wave B2 (auto-claim): hide the per-card «Взять в работу» for a solo seller — no queue to route.
  const isSoloSeller = useIsSoloSeller();

  const handleClaim = (e: React.MouseEvent, dealId: number) => {
    e.stopPropagation(); // don't open the deal — just take ownership from the queue
    claimMut.mutate(dealId, {
      onSuccess: () => toast.success(t('dealsKanban.claimed')),
      onError: (err) => toast.error(translateApiError(err)),
    });
  };

  const grouped = useMemo(() => {
    const map: Record<string, Deal[]> = {};
    const stageOrder = (stages ?? []).map((s) => s.code);
    stageOrder.forEach((code) => (map[code] = []));
    for (const d of deals) {
      const code = d.stage_code || 'UNKNOWN';
      if (!map[code]) map[code] = [];
      map[code].push(d);
    }
    return stageOrder.length
      ? stageOrder.map((code) => ({
          code,
          // Column header by CODE (RU-only `stage.name` would leak into the EN UI);
          // the DB name is the fallback only for a stage code this build predates.
          name: DEAL_STAGE_LABEL_KEY[code]
            ? t(DEAL_STAGE_LABEL_KEY[code])
            : (stages?.find((s) => s.code === code)?.name ?? code),
          deals: map[code] ?? [],
        }))
      : Object.entries(map).map(([code, list]) => ({ code, name: code, deals: list }));
  }, [deals, stages, t]);

  return (
    <ScrollArea className="w-full">
      <div className="flex min-w-max gap-3 pb-2">
        {grouped.map((col) => {
          const total = sumMoney(col.deals.map((d) => d.total_value));
          return (
            <div
              key={col.code}
              className="flex w-72 shrink-0 flex-col gap-2 rounded-lg border bg-muted/30 p-2"
            >
              <div className="flex items-center justify-between px-1 pt-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {DEAL_STAGE_LABEL_KEY[col.code] ? t(DEAL_STAGE_LABEL_KEY[col.code]) : col.name}
                  </span>
                  <Badge variant="secondary" className="text-xs">
                    {col.deals.length}
                  </Badge>
                </div>
                {total > 0 ? (
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {format(total)}
                  </span>
                ) : null}
              </div>
              <div className="flex flex-col gap-2">
                {col.deals.length === 0 ? (
                  <div className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
                    {t('dealsKanban.empty')}
                  </div>
                ) : (
                  col.deals.map((d) => (
                    <Card
                      key={d.id}
                      className={cn(
                        'cursor-pointer border-muted/50 transition-colors hover:border-primary/40 hover:shadow-sm',
                      )}
                      onClick={() => onOpen?.(d)}
                    >
                      <CardContent className="space-y-1 p-3">
                        <div className="flex items-start justify-between gap-2">
                          <span className="truncate text-xs font-medium">
                            {d.title || t('dealsKanban.untitled', { id: d.id })}
                          </span>
                          <span className="shrink-0 font-mono text-xs text-muted-foreground">
                            #{d.id}
                          </span>
                        </div>
                        {d.company_name ? (
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Handshake className="h-3 w-3" aria-hidden="true" />
                            <span className="truncate">{d.company_name}</span>
                          </div>
                        ) : null}
                        {d.total_value && Number(d.total_value) > 0 ? (
                          <div className="text-xs font-semibold tabular-nums">
                            {format(Number(d.total_value))}
                          </div>
                        ) : null}
                        {/* Ownership keys off assigned_to (the id) — NOT the name, which is empty for
                            invited members (blank full name) and redacted across tenants, so a claimed
                            deal would otherwise render as unclaimed. Name is display-only with a fallback. */}
                        {/* W3 aging-counter: непринятая пред-КП заявка показывает, сколько она
                            ждёт (warning < 24ч, destructive дальше) — Bitrix24-паттерн счётчиков. */}
                        {isUnclaimedRfq(d) && formatWaiting(t, d.created_at) ? (
                          <div className={cn(
                            'flex items-center gap-1 text-xs font-medium',
                            (waitingHours(d.created_at) ?? 0) >= 24 ? 'text-destructive' : 'text-warning',
                          )}>
                            <Clock className="h-3 w-3" aria-hidden="true" />
                            {formatWaiting(t, d.created_at)}
                          </div>
                        ) : null}
                        {d.assigned_to != null ? (
                          <Badge variant="secondary" className="gap-1 text-xs font-normal">
                            <UserCheck className="h-3 w-3" aria-hidden="true" />
                            <span className="truncate">{d.assigned_to_name || t('dealsKanban.assigned')}</span>
                          </Badge>
                        ) : isSoloSeller ? null : (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-6 w-full text-xs"
                            disabled={claimMut.isPending}
                            onClick={(e) => handleClaim(e, d.id)}
                          >
                            {claimMut.isPending && claimMut.variables === d.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                            ) : null}
                            {t('dealsKanban.claim')}
                          </Button>
                        )}
                      </CardContent>
                    </Card>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}
