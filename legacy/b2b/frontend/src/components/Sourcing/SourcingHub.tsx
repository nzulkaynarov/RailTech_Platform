import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Package, AlertCircle, CheckCircle2, Link2, ExternalLink, ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { cn } from '@/lib/utils';
import { useFlowStore, type RequestItem, type MatchStatus } from '@/store/flowStore';

/* ─── Master Catalog demo data ─────────────────────────────────────── */

interface CatalogProduct {
  id: string;
  name: string;
  sku: string;
  manufacturer: string;
}

const masterCatalog: CatalogProduct[] = [
  { id: 'MC-1', name: 'Подшипник роликовый 42726 ГОСТ 8328-75', sku: 'BRG-042726', manufacturer: 'СКФ' },
  { id: 'MC-2', name: 'Подшипник роликовый 32726', sku: 'BRG-032726', manufacturer: 'ЕПК' },
  { id: 'MC-3', name: 'Смазка ЦИАТИМ-201 ГОСТ 6267-74', sku: 'LUB-CIATIM201', manufacturer: 'ВНИИНП' },
  { id: 'MC-4', name: 'Смазка Литол-24', sku: 'LUB-LITOL24', manufacturer: 'ВНИИНП' },
  { id: 'MC-5', name: 'Подшипник шариковый 6-180306', sku: 'BRG-180306', manufacturer: 'СКФ' },
  { id: 'MC-6', name: 'Масло трансмиссионное ТСп-15К', sku: 'LUB-TSP15K', manufacturer: 'Газпромнефть' },
];

/* ─── Status helpers ───────────────────────────────────────────────── */

const statusVariantMap: Record<MatchStatus, 'success' | 'warning' | 'danger'> = {
  matched: 'success',
  partial: 'warning',
  not_found: 'danger',
};

const statusIconMap: Record<MatchStatus, React.ReactNode> = {
  matched: <CheckCircle2 className="h-3.5 w-3.5" />,
  partial: <AlertCircle className="h-3.5 w-3.5" />,
  not_found: <Package className="h-3.5 w-3.5" />,
};

/* ─── Component ────────────────────────────────────────────────────── */

export function SourcingHub() {
  const { t } = useTranslation();
  const { request } = useFlowStore();
  const items = request.items;

  const [dialogOpen, setDialogOpen] = useState(false);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [mappings, setMappings] = useState<Record<string, CatalogProduct>>({});

  /* ── KPI counts ────────────────────────────────────────────────── */

  const counts = useMemo(() => {
    let matched = 0;
    let partial = 0;
    let notFound = 0;
    for (const item of items) {
      const effectiveStatus = mappings[item.id] ? 'matched' : item.matchStatus;
      if (effectiveStatus === 'matched') matched++;
      else if (effectiveStatus === 'partial') partial++;
      else notFound++;
    }
    return { matched, partial, notFound, total: items.length };
  }, [items, mappings]);

  /* ── Catalog search filter ─────────────────────────────────────── */

  const filteredCatalog = useMemo(() => {
    if (!searchQuery.trim()) return masterCatalog;
    const q = searchQuery.toLowerCase();
    return masterCatalog.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.sku.toLowerCase().includes(q) ||
        p.manufacturer.toLowerCase().includes(q)
    );
  }, [searchQuery]);

  /* ── Handlers ──────────────────────────────────────────────────── */

  function openCatalogSearch(itemId: string) {
    setActiveItemId(itemId);
    setSearchQuery('');
    setDialogOpen(true);
  }

  function handleSelectProduct(product: CatalogProduct) {
    if (!activeItemId) return;
    setMappings((prev) => ({ ...prev, [activeItemId]: product }));
    setDialogOpen(false);
    setActiveItemId(null);
  }

  function getEffectiveStatus(item: RequestItem): MatchStatus {
    return mappings[item.id] ? 'matched' : item.matchStatus;
  }

  const activeItem = items.find((i) => i.id === activeItemId);

  /* ── Render ────────────────────────────────────────────────────── */

  return (
    <div className="space-y-4">
      {/* ── Summary KPIs ──────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-3">
        <Card className="py-3">
          <CardHeader className="pb-1 pt-0 px-4">
            <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              {t('sourcingHub.kpi.matched')}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-0">
            <div className="flex items-baseline gap-1.5">
              <span className="text-2xl font-bold text-foreground">{counts.matched}</span>
              <span className="text-sm text-muted-foreground">{t('sourcingHub.kpi.outOf', { total: counts.total })}</span>
            </div>
          </CardContent>
        </Card>

        <Card className="py-3">
          <CardHeader className="pb-1 pt-0 px-4">
            <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              {t('sourcingHub.kpi.partial')}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-0">
            <span className="text-2xl font-bold text-foreground">{counts.partial}</span>
          </CardContent>
        </Card>

        <Card className={cn('py-3', counts.notFound > 0 && 'border-destructive/40 bg-destructive/5')}>
          <CardHeader className="pb-1 pt-0 px-4">
            <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              {t('sourcingHub.kpi.notFound')}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-0">
            <span className={cn('text-2xl font-bold', counts.notFound > 0 ? 'text-destructive' : 'text-muted-foreground')}>
              {counts.notFound}
            </span>
          </CardContent>
        </Card>
      </div>

      {/* ── Items Table ───────────────────────────────────────────── */}
      <Card>
        <CardHeader className="py-3 px-4">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Package className="h-4 w-4 text-muted-foreground" />
            {t('sourcingHub.title')}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="text-xs">
                <TableHead className="w-10 px-3">{t('sourcingHub.table.num')}</TableHead>
                <TableHead className="px-3">{t('sourcingHub.table.name')}</TableHead>
                <TableHead className="px-3 w-24">{t('sourcingHub.table.article')}</TableHead>
                <TableHead className="px-3 w-32">{t('sourcingHub.table.gost')}</TableHead>
                <TableHead className="px-3 w-14 text-center">{t('sourcingHub.table.uom')}</TableHead>
                <TableHead className="px-3 w-16 text-right">{t('sourcingHub.table.qty')}</TableHead>
                <TableHead className="px-3 w-28 text-center">{t('sourcingHub.table.matchStatus')}</TableHead>
                <TableHead className="px-3 w-36 text-center">{t('sourcingHub.table.action')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item, idx) => {
                const status = getEffectiveStatus(item);
                const mapping = mappings[item.id];

                return (
                  <TableRow
                    key={item.id}
                    className="text-sm"
                  >
                    <TableCell className="px-3 py-2 text-xs text-muted-foreground font-mono">
                      {idx + 1}
                    </TableCell>
                    <TableCell className="px-3 py-2">
                      <div className="space-y-0.5">
                        <span className="font-medium text-sm leading-tight">{item.name}</span>
                        {mapping && (
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Link2 className="h-3 w-3" />
                            {t('sourcingHub.linkedTo', { name: mapping.name })}
                          </div>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="px-3 py-2 text-xs font-mono text-muted-foreground">
                      {item.article}
                    </TableCell>
                    <TableCell className="px-3 py-2 text-xs text-muted-foreground">
                      {item.gost}
                    </TableCell>
                    <TableCell className="px-3 py-2 text-xs text-center text-muted-foreground">
                      {item.uom}
                    </TableCell>
                    <TableCell className="px-3 py-2 text-sm text-right font-medium tabular-nums">
                      {item.quantity}
                    </TableCell>
                    <TableCell className="px-3 py-2 text-center">
                      <StatusBadge
                        label={t(`sourcingHub.status.${status}`)}
                        variant={statusVariantMap[status]}
                        icon={statusIconMap[status]}
                      />
                    </TableCell>
                    <TableCell className="px-3 py-2 text-center">
                      {status === 'not_found' && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs gap-1"
                          onClick={() => openCatalogSearch(item.id)}
                        >
                          <Search className="h-3 w-3" />
                          {t('sourcingHub.actions.findInCatalog')}
                        </Button>
                      )}
                      {status === 'partial' && !mapping && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs gap-1"
                          onClick={() => openCatalogSearch(item.id)}
                        >
                          <ExternalLink className="h-3 w-3" />
                          {t('sourcingHub.actions.clarify')}
                        </Button>
                      )}
                      {status === 'matched' && !mapping && (
                        <StatusBadge
                          label={t('sourcingHub.status.matched')}
                          variant="success"
                          icon={<CheckCircle2 className="h-3.5 w-3.5" />}
                        />
                      )}
                      {mapping && (
                        <StatusBadge
                          label={t('sourcingHub.actions.linked')}
                          variant="success"
                          icon={<CheckCircle2 className="h-3.5 w-3.5" />}
                        />
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* ── Catalog Search Dialog ─────────────────────────────────── */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <Search className="h-4 w-4" />
              {t('sourcingHub.dialog.title')}
            </DialogTitle>
            <DialogDescription className="text-xs">
              {activeItem && (
                <>
                  {t('sourcingHub.dialog.item')}: <span className="font-medium text-foreground">{activeItem.name}</span>
                  {activeItem.gost && <> ({activeItem.gost})</>}
                </>
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder={t('sourcingHub.dialog.searchPlaceholder')}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 h-9 text-sm"
            />
          </div>

          <ScrollArea className="h-[300px] -mx-1 px-1">
            <div className="space-y-1">
              {filteredCatalog.length === 0 && (
                <div className="text-center text-sm text-muted-foreground py-8">
                  {t('sourcingHub.dialog.noResults')}
                </div>
              )}
              {filteredCatalog.map((product) => (
                <Button
                  key={product.id}
                  type="button"
                  variant="outline"
                  onClick={() => handleSelectProduct(product)}
                  className={cn(
                    'w-full text-left rounded-md h-auto px-3 py-2.5 transition-colors justify-start',
                    'hover:bg-accent hover:border-primary/30',
                  )}
                >
                  <div className="flex items-start justify-between gap-2 w-full">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium leading-tight truncate">{product.name}</p>
                      <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                        <span className="font-mono">{product.sku}</span>
                        <span>{product.manufacturer}</span>
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
                  </div>
                </Button>
              ))}
            </div>
          </ScrollArea>

          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
