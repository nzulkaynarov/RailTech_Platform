import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Check, Loader2, Sparkles, AlertTriangle } from 'lucide-react';
import { QuoteItem, CatalogMatch } from '@/api/crmApi';
import { useMatchCatalog, useUpdateQuoteItem } from '@/hooks/useCRM';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

interface AICatalogMatchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: QuoteItem[];
}

// Narrow shape for reading the backend's {error: '...'} payload off an axios error.
type AxiosLike = { response?: { status?: number; data?: { error?: string } } };

const lineName = (item: QuoteItem) => item.product_name || item.imported_raw_name || '';

export const AICatalogMatchDialog: React.FC<AICatalogMatchDialogProps> = ({ open, onOpenChange, items }) => {
  const { t } = useTranslation();
  const matchMutation = useMatchCatalog();
  const updateMutation = useUpdateQuoteItem();

  // The unmatched lines we POST. Their array order IS the line_index space the
  // backend returns, so index N here ↔ line_index N in the response.
  const unmatchedItems = useMemo(() => items.filter((item) => !item.product), [items]);

  const [matches, setMatches] = useState<CatalogMatch[]>([]);
  const [aiDisabled, setAiDisabled] = useState(false);
  const [failed, setFailed] = useState(false);
  // QuoteItem ids that have just been bound in this session (visual "done" mark).
  const [boundItemIds, setBoundItemIds] = useState<Set<number>>(new Set());
  // QuoteItem id currently being bound (spinner on its chip group).
  const [bindingItemId, setBindingItemId] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    setMatches([]);
    setAiDisabled(false);
    setFailed(false);
    setBoundItemIds(new Set());
    setBindingItemId(null);

    if (unmatchedItems.length === 0) return;

    matchMutation.mutate(
      {
        lines: unmatchedItems.map((item) => ({
          name: lineName(item),
          mpn: item.mpn || undefined,
          gost_drawing: item.gost_drawing || undefined,
        })),
      },
      {
        onSuccess: (data) => setMatches(data.matches),
        onError: (error) => {
          const axiosError = error as AxiosLike;
          if (axiosError.response?.data?.error === 'AI_DISABLED' || axiosError.response?.status === 503) {
            setAiDisabled(true);
          } else {
            setFailed(true);
          }
        },
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Map line_index → its candidates for O(1) lookup while rendering.
  const matchByLineIndex = useMemo(() => {
    const map = new Map<number, CatalogMatch>();
    matches.forEach((match) => map.set(match.line_index, match));
    return map;
  }, [matches]);

  const handleBind = async (item: QuoteItem, productId: number) => {
    setBindingItemId(item.id);
    try {
      await updateMutation.mutateAsync({ id: item.id, data: { product: productId } });
      setBoundItemIds((prev) => new Set(prev).add(item.id));
      toast.success(t('aiMatch.bound'));
    } catch {
      toast.error(t('errors.operationFailed'));
    } finally {
      setBindingItemId(null);
    }
  };

  const isLoading = matchMutation.isPending;
  const hasAnyCandidates = matches.length > 0;

  const renderBody = () => {
    if (unmatchedItems.length === 0) {
      return (
        <Alert>
          <Check className="size-4" aria-hidden="true" />
          <AlertTitle>{t('aiMatch.allMatched')}</AlertTitle>
          <AlertDescription>{t('aiMatch.allMatchedDesc')}</AlertDescription>
        </Alert>
      );
    }

    if (isLoading) {
      return (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            {t('aiMatch.loading')}
          </div>
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      );
    }

    if (aiDisabled) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" aria-hidden="true" />
          <AlertTitle>{t('aiMatch.aiDisabled')}</AlertTitle>
          <AlertDescription>{t('aiMatch.aiDisabledDesc')}</AlertDescription>
        </Alert>
      );
    }

    if (failed) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" aria-hidden="true" />
          <AlertTitle>{t('errors.operationFailed')}</AlertTitle>
          <AlertDescription>{t('aiMatch.retryHint')}</AlertDescription>
        </Alert>
      );
    }

    if (!hasAnyCandidates) {
      return (
        <Alert>
          <AlertTriangle className="size-4" aria-hidden="true" />
          <AlertTitle>{t('aiMatch.noMatches')}</AlertTitle>
          <AlertDescription>{t('aiMatch.noMatchesDesc')}</AlertDescription>
        </Alert>
      );
    }

    return (
      <ScrollArea className="max-h-[55vh] pr-4">
        <div className="flex flex-col gap-4">
          {unmatchedItems.map((item, index) => {
            const match = matchByLineIndex.get(index);
            const isBound = boundItemIds.has(item.id);
            const isBinding = bindingItemId === item.id;

            return (
              <div key={item.id} className="rounded-md border p-3">
                <div className="mb-2 flex items-center gap-2">
                  {isBound ? (
                    <Check className="size-4 shrink-0 text-success" aria-hidden="true" />
                  ) : (
                    <AlertTriangle className="size-4 shrink-0 text-warning" aria-hidden="true" />
                  )}
                  <span className="text-sm font-semibold">{lineName(item)}</span>
                  {item.mpn && (
                    <Badge variant="outline" className="font-mono text-xs">{item.mpn}</Badge>
                  )}
                </div>

                {isBound ? (
                  <p className="text-xs text-success">{t('aiMatch.bound')}</p>
                ) : !match ? (
                  <p className="text-xs text-muted-foreground">{t('aiMatch.noMatches')}</p>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    {isBinding && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden="true" />}
                    {match.candidates.map((candidate) => (
                      <Tooltip key={candidate.product_id}>
                        <TooltipTrigger asChild>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-auto gap-2 py-1.5"
                            disabled={isBinding}
                            onClick={() => handleBind(item, candidate.product_id)}
                          >
                            <span className="text-sm font-medium">{candidate.name}</span>
                            <Badge variant="secondary" className="font-mono text-xs">{candidate.sku}</Badge>
                            <Badge variant="default" className="text-xs">
                              {Math.round(candidate.confidence * 100)}%
                            </Badge>
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-xs">
                          {candidate.reason || t('aiMatch.bind')}
                        </TooltipContent>
                      </Tooltip>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </ScrollArea>
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" aria-hidden="true" />
            {t('aiMatch.title')}
          </DialogTitle>
          <DialogDescription>{t('aiMatch.description')}</DialogDescription>
        </DialogHeader>

        <TooltipProvider>{renderBody()}</TooltipProvider>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
