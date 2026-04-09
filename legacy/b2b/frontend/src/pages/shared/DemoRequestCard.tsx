import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { FileSpreadsheet, ChevronRight } from 'lucide-react';
import { useFlowStore, requestStatusLabels, requestStatusColors } from '@/store/flowStore';

export function DemoRequestCard({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation();
  const { request } = useFlowStore();
  const matchedCount = request.items.filter((i) => i.matchStatus === 'matched').length;
  const totalItems = request.items.length;

  return (
    <Card className="cursor-pointer hover:border-primary/50 transition-colors py-0 gap-0" onClick={onOpen}>
      <CardContent className="px-4 py-4">
        <div className="flex items-center gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
            <FileSpreadsheet className="h-5 w-5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium">{request.number}</span>
              <Badge variant="outline" className={cn('text-xs', requestStatusColors[request.status])}>
                {t(requestStatusLabels[request.status])}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {request.clientName} · {totalItems} {t('pages.common.items')} · {matchedCount} {t('pages.common.found')} · {request.createdAt}
            </p>
          </div>
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}
