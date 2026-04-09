import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { cn } from '@/lib/utils';
import {
  Train,
  Package,
  Wrench,
  Calculator,
  TrendingUp,
  Hash,
} from 'lucide-react';
import type { RequestItem } from '@/store/flowStore';
import { useCurrencyStore } from '@/store/currencyStore';

/* ─── Types ────────────────────────────────────────────────────────────── */

type Domain = 'RAILWAY_MACHINERY' | 'GENERAL_GOODS' | 'SERVICES';

interface QuoteBuilderGridProps {
  items: RequestItem[];
  onUpdateMargin: (itemId: string, margin: number) => void;
  defaultMargin?: number;
}

/* ─── Domain helpers ───────────────────────────────────────────────────── */

const DOMAIN_META: Record<
  Domain,
  { labelKey: string; icon: React.ReactNode; color: string }
> = {
  RAILWAY_MACHINERY: {
    labelKey: 'domains.short.RAILWAY_MACHINERY',
    icon: <Train className="size-4" />,
    color: 'bg-[var(--color-chart-1)]/10 text-[var(--color-chart-1)]',
  },
  GENERAL_GOODS: {
    labelKey: 'domains.short.GENERAL_GOODS',
    icon: <Package className="size-4" />,
    color: 'bg-[var(--color-chart-2)]/10 text-[var(--color-chart-2)]',
  },
  SERVICES: {
    labelKey: 'domains.short.SERVICES',
    icon: <Wrench className="size-4" />,
    color: 'bg-[var(--color-chart-3)]/10 text-[var(--color-chart-3)]',
  },
};

function assignDomain(article: string): Domain {
  const prefix = article.split('-')[0]?.toUpperCase() ?? '';
  if (prefix === 'MAT' || prefix === 'MET') return 'RAILWAY_MACHINERY';
  if (prefix === 'ELC') return 'GENERAL_GOODS';
  if (prefix === 'BRG' || prefix === 'LUB') return 'SERVICES';
  return 'RAILWAY_MACHINERY';
}

/* ─── Currency formatting ──────────────────────────────────────────────── */

function fmt(value: number): string {
  return useCurrencyStore.getState().format(value);
}

function fmtPercent(value: number): string {
  return `${value.toLocaleString('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`;
}

/* ─── Row calculation ──────────────────────────────────────────────────── */

interface CalculatedRow {
  item: RequestItem;
  domain: Domain;
  basePrice: number;
  logisticsCost: number;
  customsDuty: number;
  landedCost: number;
  marginPercent: number;
  finalPrice: number;
  finalPriceWithVAT: number;
  lineTotal: number;
}

function calculateRow(
  item: RequestItem,
  marginOverride: number | undefined,
  defaultMargin: number
): CalculatedRow {
  const domain = assignDomain(item.article);
  const marginPercent = marginOverride ?? item.marginPercent ?? defaultMargin;

  const basePrice = item.inSellerStock
    ? (item.partnerPriceFCA ?? 0)
    : (item.rfqPrice ?? item.partnerPriceFCA ?? 0);

  const logisticsCost = basePrice * 0.08;
  const customsDuty = basePrice * 0.05;
  const landedCost = basePrice + logisticsCost + customsDuty;
  const finalPrice = landedCost * (1 + marginPercent / 100);
  const finalPriceWithVAT = finalPrice * 1.12;
  const lineTotal = finalPriceWithVAT * item.quantity;

  return {
    item,
    domain,
    basePrice,
    logisticsCost,
    customsDuty,
    landedCost,
    marginPercent,
    finalPrice,
    finalPriceWithVAT,
    lineTotal,
  };
}

/* ─── Component ────────────────────────────────────────────────────────── */

export function QuoteBuilderGrid({
  items,
  onUpdateMargin,
  defaultMargin = 15,
}: QuoteBuilderGridProps) {
  const { t } = useTranslation();
  const [marginOverrides, setMarginOverrides] = useState<
    Record<string, number>
  >({});

  const handleMarginChange = useCallback(
    (itemId: string, value: string) => {
      const parsed = parseFloat(value);
      if (!isNaN(parsed) && parsed >= 0 && parsed <= 100) {
        setMarginOverrides((prev) => ({ ...prev, [itemId]: parsed }));
        onUpdateMargin(itemId, parsed);
      }
    },
    [onUpdateMargin]
  );

  const calculatedRows = useMemo(
    () =>
      items.map((item) =>
        calculateRow(item, marginOverrides[item.id], defaultMargin)
      ),
    [items, marginOverrides, defaultMargin]
  );

  const rowsByDomain = useMemo(() => {
    const grouped: Record<Domain, CalculatedRow[]> = {
      RAILWAY_MACHINERY: [],
      GENERAL_GOODS: [],
      SERVICES: [],
    };
    for (const row of calculatedRows) {
      grouped[row.domain].push(row);
    }
    return grouped;
  }, [calculatedRows]);

  const totals = useMemo(() => {
    const subtotalWithoutVAT = calculatedRows.reduce(
      (sum, r) => sum + r.finalPrice * r.item.quantity,
      0
    );
    const vatAmount = subtotalWithoutVAT * 0.12;
    const totalWithVAT = subtotalWithoutVAT + vatAmount;
    const avgMargin =
      calculatedRows.length > 0
        ? calculatedRows.reduce((sum, r) => sum + r.marginPercent, 0) /
          calculatedRows.length
        : 0;
    const totalItems = calculatedRows.reduce(
      (sum, r) => sum + r.item.quantity,
      0
    );

    return { subtotalWithoutVAT, vatAmount, totalWithVAT, avgMargin, totalItems };
  }, [calculatedRows]);

  const numCellClass = 'text-right tabular-nums';

  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Calculator className="size-5" />
            {t('quote.builder')}
          </CardTitle>
          <Badge variant="outline" className="font-mono text-xs">
            {t('catalog.totalItems', { count: items.length })}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="p-0">
        <Tabs defaultValue="RAILWAY_MACHINERY">
          <div className="border-b px-4">
            <TabsList variant="line">
              {(
                ['RAILWAY_MACHINERY', 'GENERAL_GOODS', 'SERVICES'] as Domain[]
              ).map((domain) => {
                const meta = DOMAIN_META[domain];
                const count = rowsByDomain[domain].length;
                return (
                  <TabsTrigger
                    key={domain}
                    value={domain}
                    className="gap-1.5 text-xs"
                  >
                    {meta.icon}
                    {t(meta.labelKey)}
                    {count > 0 && (
                      <Badge
                        variant="secondary"
                        className="ml-1 h-5 min-w-5 px-1 text-xs"
                      >
                        {count}
                      </Badge>
                    )}
                  </TabsTrigger>
                );
              })}
            </TabsList>
          </div>

          {(
            ['RAILWAY_MACHINERY', 'GENERAL_GOODS', 'SERVICES'] as Domain[]
          ).map((domain) => (
            <TabsContent key={domain} value={domain} className="mt-0">
              <DomainTable
                rows={rowsByDomain[domain]}
                numCellClass={numCellClass}
                onMarginChange={handleMarginChange}
                marginOverrides={marginOverrides}
              />
            </TabsContent>
          ))}
        </Tabs>

        {/* ─── Dark Totalling Panel ──────────────────────────────────── */}
        <div className="bg-foreground px-6 py-4 text-background dark:bg-foreground">
          <div className="grid grid-cols-5 gap-6">
            <TotalItem
              label={t('quote.subtotalExclVAT')}
              value={fmt(totals.subtotalWithoutVAT)}
              icon={<Calculator className="size-4 text-background/60" />}
            />
            <TotalItem
              label={t('quote.vatPercent')}
              value={fmt(totals.vatAmount)}
              icon={<Hash className="size-4 text-background/60" />}
            />
            <TotalItem
              label={t('quote.totalInclVAT')}
              value={fmt(totals.totalWithVAT)}
              highlight
              icon={<TrendingUp className="size-4 text-[var(--color-chart-3)]" />}
            />
            <TotalItem
              label={t('quote.avgMargin')}
              value={fmtPercent(totals.avgMargin)}
              icon={<TrendingUp className="size-4 text-background/60" />}
            />
            <TotalItem
              label={t('quote.totalItems')}
              value={t('quote.totalItemsUnit', { count: totals.totalItems })}
              icon={<Package className="size-4 text-background/60" />}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/* ─── Domain Table ─────────────────────────────────────────────────────── */

function DomainTable({
  rows,
  numCellClass,
  onMarginChange,
  marginOverrides,
}: {
  rows: CalculatedRow[];
  numCellClass: string;
  onMarginChange: (itemId: string, value: string) => void;
  marginOverrides: Record<string, number>;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
        {t('quote.noItemsInCategory')}
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="bg-muted/30 text-xs">
          <TableHead className="w-10 text-center">№</TableHead>
          <TableHead className="min-w-[200px]">{t('catalog.table.name')}</TableHead>
          <TableHead className="w-24">{t('quote.article')}</TableHead>
          <TableHead className="w-28">{t('quote.gost')}</TableHead>
          <TableHead className="w-12 text-center">{t('quote.unitShort')}</TableHead>
          <TableHead className={cn('w-14', numCellClass)}>{t('quote.quantity')}</TableHead>
          <TableHead className={cn('w-24', numCellClass)}>
            {t('quote.priceFCA')}
          </TableHead>
          <TableHead className={cn('w-24', numCellClass)}>
            {t('quote.logisticsCost')}
          </TableHead>
          <TableHead className={cn('w-24', numCellClass)}>{t('quote.customsDuty')}</TableHead>
          <TableHead className={cn('w-28', numCellClass)}>
            {t('quote.landedCost')}
          </TableHead>
          <TableHead className="w-20 text-center">{t('quote.marginPercent')}</TableHead>
          <TableHead className={cn('w-28', numCellClass)}>
            {t('quote.priceExclVAT')}
          </TableHead>
          <TableHead className={cn('w-28', numCellClass)}>{t('quote.vatPercent')}</TableHead>
          <TableHead className={cn('w-28', numCellClass)}>
            {t('quote.priceInclVAT')}
          </TableHead>
          <TableHead className={cn('w-32', numCellClass)}>{t('quote.lineTotal')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => {
          const vatPerUnit = row.finalPriceWithVAT - row.finalPrice;
          const currentMargin =
            marginOverrides[row.item.id] ?? row.marginPercent;

          return (
            <TableRow
              key={row.item.id}
              className={cn(
                'text-xs',
                index % 2 === 0 ? 'bg-background' : 'bg-muted/20'
              )}
            >
              <TableCell className="text-center text-muted-foreground">
                {index + 1}
              </TableCell>
              <TableCell
                className="max-w-[200px] truncate font-medium"
                title={row.item.name}
              >
                {row.item.name}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {row.item.article}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {row.item.gost || '—'}
              </TableCell>
              <TableCell className="text-center text-muted-foreground">
                {row.item.uom}
              </TableCell>
              <TableCell className={cn(numCellClass, 'font-medium')}>
                {row.item.quantity}
              </TableCell>
              <TableCell className={numCellClass}>{fmt(row.basePrice)}</TableCell>
              <TableCell className={cn(numCellClass, 'text-muted-foreground')}>
                {fmt(row.logisticsCost)}
              </TableCell>
              <TableCell className={cn(numCellClass, 'text-muted-foreground')}>
                {fmt(row.customsDuty)}
              </TableCell>
              <TableCell className={cn(numCellClass, 'font-medium')}>
                {fmt(row.landedCost)}
              </TableCell>
              <TableCell className="text-center">
                <Input
                  type="number"
                  min={0}
                  max={100}
                  step={0.5}
                  value={currentMargin}
                  onChange={(e) =>
                    onMarginChange(row.item.id, e.target.value)
                  }
                  className="h-7 w-16 mx-auto text-center text-xs tabular-nums"
                />
              </TableCell>
              <TableCell className={cn(numCellClass, 'font-medium')}>
                {fmt(row.finalPrice)}
              </TableCell>
              <TableCell className={cn(numCellClass, 'text-muted-foreground')}>
                {fmt(vatPerUnit)}
              </TableCell>
              <TableCell className={cn(numCellClass, 'font-medium')}>
                {fmt(row.finalPriceWithVAT)}
              </TableCell>
              <TableCell
                className={cn(
                  numCellClass,
                  'font-semibold text-foreground'
                )}
              >
                {fmt(row.lineTotal)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/* ─── Total Item ───────────────────────────────────────────────────────── */

function TotalItem({
  label,
  value,
  highlight,
  icon,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="flex items-center gap-1.5 text-xs text-background/60">
        {icon}
        {label}
      </span>
      <span
        className={cn(
          'text-lg font-semibold tabular-nums',
          highlight ? 'text-[var(--color-chart-3)]' : 'text-background'
        )}
      >
        {value}
      </span>
    </div>
  );
}
