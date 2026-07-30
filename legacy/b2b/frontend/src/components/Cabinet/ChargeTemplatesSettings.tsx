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
import type { ChargeTemplate } from '@/api/crmApi';
import { chargeTypeLabelKey, deliveryBasisLabelKey } from '@/lib/codes';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';

/**
 * Company-Admin org-admin zone: manage the company's per-Incoterm charge templates.
 * Selecting a basis on a КП auto-applies these rows; if empty, the platform's global
 * defaults are used as fallback (handled server-side).
 * §2.4: a data table — full width (ResponsiveDataTable, repo convention), no reading cap.
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

  const columns: ResponsiveColumn<ChargeTemplate>[] = [
    {
      id: 'basis',
      header: t('chargeTemplates.basis'),
      mobileTitle: true,
      cell: (tpl) => <Badge variant="outline">{tpl.delivery_basis}</Badge>,
    },
    {
      id: 'chargeType',
      header: t('chargeTemplates.chargeType'),
      cell: (tpl) => (
        <span className="text-sm font-medium">
          {chargeTypeLabelKey(tpl.charge_type) ? t(chargeTypeLabelKey(tpl.charge_type)) : (tpl.charge_type_name ?? tpl.charge_type)}
          {tpl.is_deduction ? (
            <Badge variant="secondary" className="ml-2">{t('quote.charges.discount')}</Badge>
          ) : null}
        </span>
      ),
    },
    {
      id: 'default',
      header: t('chargeTemplates.default'),
      cell: (tpl) => (
        <span className="font-mono text-sm tabular-nums">
          {tpl.default_rate_percent != null ? `${tpl.default_rate_percent}%` : tpl.default_amount}
        </span>
      ),
    },
    {
      id: 'actions',
      header: '',
      className: 'w-12',
      mobileActions: true,
      cell: (tpl) => (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button
              variant="ghost"
              size="icon-xs"
              className="text-muted-foreground hover:text-destructive"
              title={t('common.delete')}
              aria-label={t('common.delete')}
            >
              <Trash2 className="size-3" />
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('chargeTemplates.deleteTitle')}</AlertDialogTitle>
              <AlertDialogDescription>
                {t('chargeTemplates.deleteConfirm')}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
              {/* Кнопка гаснет на время запроса: без этого второй клик отправлял
                  удаление повторно (аудит UI, U4). */}
              <AlertDialogAction
                onClick={() => deleteMut.mutate(tpl.id)}
                disabled={deleteMut.isPending}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                {t('common.delete')}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      ),
    },
  ];

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

      <Card>
        <CardContent className="p-0">
          {templates.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">
              {t('chargeTemplates.empty')}
            </p>
          ) : (
            <ResponsiveDataTable
              columns={columns}
              rows={templates}
              getRowId={(tpl) => tpl.id}
            />
          )}
        </CardContent>
      </Card>

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
                <SelectItem key={b.id} value={b.code}>
                  {b.code} — {deliveryBasisLabelKey(b.code) ? t(deliveryBasisLabelKey(b.code)) : b.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={chargeType} onValueChange={setChargeType}>
            <SelectTrigger className="h-9 w-52" aria-label={t('chargeTemplates.chargeType')}>
              <SelectValue placeholder={t('chargeTemplates.chargeType')} />
            </SelectTrigger>
            <SelectContent>
              {chargeTypes.map((ct) => (
                <SelectItem key={ct.id} value={ct.code}>{chargeTypeLabelKey(ct.code) ? t(chargeTypeLabelKey(ct.code)) : ct.name}</SelectItem>
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
