import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Plus, Trash2, Loader2, FileStack } from 'lucide-react';
import {
  useChargeTemplates,
  useChargeTypes,
  useCreateChargeTemplate,
  useDeleteChargeTemplate,
} from '@/hooks/useCRM';
import { useDeliveryBases } from '@/hooks/useMasterData';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';

/**
 * Company-Admin org-admin zone: manage the company's per-Incoterm charge templates.
 * Selecting a basis on a КП auto-applies these rows; if empty, the platform's global
 * defaults are used as fallback (handled server-side).
 */
export function ChargeTemplatesSettings() {
  const { t } = useTranslation();
  const { data: templates = [], isLoading } = useChargeTemplates();
  const { data: chargeTypes = [] } = useChargeTypes();
  const { data: bases = [] } = useDeliveryBases();
  const createMut = useCreateChargeTemplate();
  const deleteMut = useDeleteChargeTemplate();

  const [basis, setBasis] = useState('');
  const [chargeType, setChargeType] = useState('');
  const [value, setValue] = useState('');
  const [mode, setMode] = useState<'fixed' | 'percent'>('fixed');
  const [kind, setKind] = useState<'charge' | 'discount'>('charge');

  async function handleAdd() {
    if (!basis || !chargeType) return;
    try {
      await createMut.mutateAsync({
        delivery_basis: basis,
        charge_type: chargeType,
        is_deduction: kind === 'discount',
        ...(mode === 'percent'
          ? { default_rate_percent: value || '0' }
          : { default_amount: value || '0' }),
      });
      toast.success(t('chargeTemplates.added'));
      setChargeType('');
      setValue('');
    } catch (err) {
      type AxiosLike = { response?: { data?: { detail?: string; charge_type?: string } } };
      const data = (err as AxiosLike)?.response?.data;
      const detail = data?.detail ?? data?.charge_type;
      toast.error(
        detail === 'TEMPLATE_ALREADY_EXISTS'
          ? t('chargeTemplates.duplicate')
          : String(detail ?? (err instanceof Error ? err.message : t('errors.operationFailed'))),
      );
    }
  }

  if (isLoading) {
    return (
      <div className="flex p-10 justify-center" role="status">
        <Loader2 className="h-8 w-8 text-muted-foreground animate-spin" aria-hidden="true" />
        <span className="sr-only">{t('common.loading')}</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
          <FileStack className="h-5 w-5 text-primary" aria-hidden="true" />
          {t('chargeTemplates.title')}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('chargeTemplates.subtitle')}</p>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="border-b border-border bg-muted/50 text-xs">
              <TableHead className="p-4">{t('chargeTemplates.basis')}</TableHead>
              <TableHead className="p-4">{t('chargeTemplates.chargeType')}</TableHead>
              <TableHead className="p-4">{t('chargeTemplates.default')}</TableHead>
              <TableHead className="p-4 w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {templates.map((tpl) => (
              <TableRow key={tpl.id} className="transition-colors hover:bg-muted/40">
                <TableCell className="p-4">
                  <Badge variant="outline">{tpl.delivery_basis}</Badge>
                </TableCell>
                <TableCell className="p-4 text-sm font-medium">
                  {tpl.charge_type_name ?? tpl.charge_type}
                  {tpl.is_deduction ? (
                    <Badge variant="secondary" className="ml-2">{t('quote.charges.discount')}</Badge>
                  ) : null}
                </TableCell>
                <TableCell className="p-4 text-sm font-mono tabular-nums">
                  {tpl.default_rate_percent != null
                    ? `${tpl.default_rate_percent}%`
                    : tpl.default_amount}
                </TableCell>
                <TableCell className="p-4">
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => deleteMut.mutate(tpl.id)}
                    className="text-muted-foreground hover:text-destructive"
                    title={t('common.delete')}
                  >
                    <Trash2 className="size-3" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {templates.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="p-8 text-center text-muted-foreground">
                  {t('chargeTemplates.empty')}
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </div>

      <div className="rounded-2xl border border-border bg-muted/40 p-6">
        <h4 className="mb-4 flex items-center gap-2 text-base font-bold text-foreground">
          <Plus className="h-4 w-4 text-primary" aria-hidden="true" />
          {t('chargeTemplates.add')}
        </h4>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={basis} onValueChange={setBasis}>
            <SelectTrigger className="h-9 w-44" aria-label={t('chargeTemplates.basis')}>
              <SelectValue placeholder={t('chargeTemplates.basis')} />
            </SelectTrigger>
            <SelectContent>
              {bases.map((b) => (
                <SelectItem key={b.id} value={b.code}>{b.code} — {b.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={chargeType} onValueChange={setChargeType}>
            <SelectTrigger className="h-9 w-52" aria-label={t('chargeTemplates.chargeType')}>
              <SelectValue placeholder={t('chargeTemplates.chargeType')} />
            </SelectTrigger>
            <SelectContent>
              {chargeTypes.map((ct) => (
                <SelectItem key={ct.id} value={ct.code}>{ct.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <ToggleGroup type="single" value={kind} onValueChange={(v) => v && setKind(v as 'charge' | 'discount')} variant="outline" size="sm">
            <ToggleGroupItem value="charge">{t('quote.charges.charge')}</ToggleGroupItem>
            <ToggleGroupItem value="discount">{t('quote.charges.discount')}</ToggleGroupItem>
          </ToggleGroup>
          <ToggleGroup type="single" value={mode} onValueChange={(v) => v && setMode(v as 'fixed' | 'percent')} variant="outline" size="sm">
            <ToggleGroupItem value="fixed">{t('quote.charges.sum')}</ToggleGroupItem>
            <ToggleGroupItem value="percent">%</ToggleGroupItem>
          </ToggleGroup>
          <Input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            placeholder={mode === 'percent' ? '%' : t('quote.charges.amount')}
            className="h-9 w-28"
          />
          <Button onClick={handleAdd} disabled={!basis || !chargeType || createMut.isPending}>
            {createMut.isPending ? <Loader2 className="size-3 animate-spin" /> : <Plus className="size-3" />}
            {t('common.add')}
          </Button>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">{t('chargeTemplates.hint')}</p>
      </div>
    </div>
  );
}

export default ChargeTemplatesSettings;
