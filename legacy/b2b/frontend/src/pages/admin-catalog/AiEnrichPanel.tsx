import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatHSCode } from '@/lib/hsCode';

import { ENRICH_FIELD_LABEL_KEY, type EnrichField, type ProductFormState } from './useProductForm';

/**
 * Панель предложений ИИ (Akeneo AI suggestions / Shopify Magic): ИИ ПРЕДЛАГАЕТ, решает человек.
 * По КАЖДОМУ полю видно, что было и что предлагается; применяется только отмеченное и только
 * по кнопке. Характеристики сворачиваются в «N строк» — лишнюю строку можно отклонить отдельно.
 * До этой волны обогащение патчило черновик МОЛЧА, а проверенный сервером код ТН ВЭД клиент
 * вообще не читал.
 *
 * Вынесена из `ProductFormSheet.tsx` отдельным файлом: с панелью внутри форма подошла
 * к 499 строкам при лимите 500, то есть следующая же правка нарушила бы конвенцию.
 */
export function AiEnrichPanel({ form }: { form: ProductFormState }) {
  const { t } = useTranslation();
  const [specsExpanded, setSpecsExpanded] = useState(false);
  const {
    enrichProposals, rejectedFields, rejectedSpecKeys, enrichAcceptedCount,
    toggleEnrichField, toggleEnrichSpec, applyEnrich, dismissEnrich, draft,
  } = form;
  if (enrichProposals.length === 0) return null;
  const currentSpecsCount = Object.keys(draft.specifications ?? {}).length;
  const renderValue = (field: EnrichField, value: string) =>
    field === 'hs_code' && value ? formatHSCode(value) : value || '—';

  return (
    <Card className="border-info/40 bg-info/5">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">
          {t('adminCatalog.aiEnrich.panelTitle', { count: enrichProposals.length })}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">{t('adminCatalog.aiEnrich.panelHint')}</p>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead className="text-xs">{t('adminCatalog.aiEnrich.columnField')}</TableHead>
                <TableHead className="text-xs">{t('adminCatalog.aiEnrich.columnCurrent')}</TableHead>
                <TableHead className="text-xs">{t('adminCatalog.aiEnrich.columnSuggested')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {enrichProposals.map((proposal) => (
                <TableRow key={proposal.field} className="align-top">
                  <TableCell className="w-8">
                    <Checkbox
                      checked={!rejectedFields.has(proposal.field)}
                      onCheckedChange={() => toggleEnrichField(proposal.field)}
                      aria-label={t(ENRICH_FIELD_LABEL_KEY[proposal.field])}
                    />
                  </TableCell>
                  <TableCell className="text-xs font-medium">
                    {t(ENRICH_FIELD_LABEL_KEY[proposal.field])}
                  </TableCell>
                  <TableCell className="text-xs whitespace-pre-wrap break-words text-muted-foreground">
                    {proposal.specs
                      ? t('adminCatalog.aiEnrich.specsRows', { count: currentSpecsCount })
                      : renderValue(proposal.field, proposal.current)}
                  </TableCell>
                  <TableCell className="text-xs whitespace-pre-wrap break-words">
                    {proposal.specs ? (
                      <Button
                        type="button"
                        variant="link"
                        size="sm"
                        className="h-auto gap-1 p-0 text-xs"
                        onClick={() => setSpecsExpanded((v) => !v)}
                        aria-expanded={specsExpanded}
                      >
                        {t('adminCatalog.aiEnrich.specsRows', { count: proposal.specs.length })}
                        <ChevronDown
                          className={`size-3.5 transition-transform ${specsExpanded ? 'rotate-180' : ''}`}
                          aria-hidden="true"
                        />
                      </Button>
                    ) : (
                      renderValue(proposal.field, proposal.next)
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {specsExpanded && !rejectedFields.has('specifications')
                && enrichProposals.find((proposal) => proposal.specs)?.specs?.map((spec) => (
                <TableRow key={spec.key} className="align-top">
                  <TableCell className="w-8">
                    <Checkbox
                      checked={!rejectedSpecKeys.has(spec.key)}
                      onCheckedChange={() => toggleEnrichSpec(spec.key)}
                      aria-label={spec.key}
                    />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{spec.key}</TableCell>
                  <TableCell className="text-xs whitespace-pre-wrap break-words text-muted-foreground">
                    {spec.current || '—'}
                  </TableCell>
                  <TableCell className="text-xs whitespace-pre-wrap break-words">{spec.next}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={applyEnrich} disabled={enrichAcceptedCount === 0}>
            {t('adminCatalog.aiEnrich.apply', { count: enrichAcceptedCount })}
          </Button>
          <Button variant="outline" size="sm" onClick={dismissEnrich}>{t('common.cancel')}</Button>
        </div>
      </CardContent>
    </Card>
  );
}
