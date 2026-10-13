import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Loader2, GitMerge } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { accountsApi } from '@/api/accountsApi';
import { translateApiError } from '@/lib/apiError';

interface MergeDuplicatesDialogProps {
  survivor: { id: number; name: string } | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * CRM Phase C — «Слить дубли». Platform Admin folds an OFFLINE placeholder company (matched by
 * INN) into the surviving real company. Auto-populate does this on KYC verify; this is the manual
 * path for placeholders discovered later.
 */
export function MergeDuplicatesDialog({ survivor, onOpenChange }: MergeDuplicatesDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<number | null>(null);

  const { data: candidates, isLoading } = useQuery({
    queryKey: ['merge-candidates', survivor?.id],
    queryFn: () => accountsApi.getMergeCandidates(survivor!.id),
    enabled: !!survivor,
  });

  const mergeMut = useMutation({
    mutationFn: (duplicateId: number) => accountsApi.mergeCompany(survivor!.id, duplicateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['companies'] });
      queryClient.invalidateQueries({ queryKey: ['merge-candidates', survivor?.id] });
      toast.success(t('adminCompanies.merge.done'));
      setPicked(null);
      onOpenChange(false);
    },
    onError: (err) => toast.error(translateApiError(err)),
  });

  return (
    <Dialog open={!!survivor} onOpenChange={(v) => !mergeMut.isPending && onOpenChange(v)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('adminCompanies.merge.title')}</DialogTitle>
          <DialogDescription>
            {t('adminCompanies.merge.description', { name: survivor?.name })}
          </DialogDescription>
        </DialogHeader>
        <div className="mt-2 space-y-2">
          {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />}
          {!isLoading && (candidates?.length ?? 0) === 0 && (
            <p className="text-sm text-muted-foreground">{t('adminCompanies.merge.empty')}</p>
          )}
          {candidates?.map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              onClick={() => setPicked(candidate.id)}
              className={`flex w-full items-center justify-between rounded-md border p-3 text-left text-sm transition-colors ${
                picked === candidate.id ? 'border-primary bg-accent' : 'border-border hover:bg-accent/50'
              }`}
            >
              <span className="font-medium">{candidate.name}</span>
              <span className="flex items-center gap-2">
                <span className="font-mono text-xs text-muted-foreground">{candidate.stated_inn}</span>
                <Badge variant="outline">{t('counterparties.offline')}</Badge>
              </span>
            </button>
          ))}
        </div>
        <DialogFooter className="mt-4 gap-2">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={mergeMut.isPending}>
            {t('adminCompanies.cancel')}
          </Button>
          <Button
            type="button"
            onClick={() => picked && mergeMut.mutate(picked)}
            disabled={!picked || mergeMut.isPending}
          >
            {mergeMut.isPending
              ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              : <GitMerge className="h-4 w-4" aria-hidden="true" />}
            {t('adminCompanies.merge.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
