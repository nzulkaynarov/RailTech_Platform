import { useTranslation } from 'react-i18next';
import {
  ArrowRight, FileSignature, HandCoins, Receipt, ScrollText, Truck,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useDealDocuments } from '@/hooks/useCRM';
import { useCurrencyStore } from '@/store/currencyStore';
import type { DealDocumentHub, DealDocumentStep } from '@/api/crmApi';
import { documentStatusLabelKey } from '@/lib/codes';

/**
 * «Цепочка сделки» — договор / счета / акты / отгрузка одним блоком на карточке сделки (F1).
 *
 * Эталон — smart-buttons карточки заказа в Odoo: связанные документы показаны счётчиками-
 * кнопками прямо в карточке, один клик до любого из них. До этого блока путь после подписания
 * договора обрывался: документы существовали, но добраться до них можно было только через
 * боковое меню, а на карточке сделки блок документов был пуст.
 *
 * Стороны и следующий шаг приходят С СЕРВЕРА (`viewer`, `next_step`), а не выводятся из
 * `activeStatus`: тот берёт первый тип компании, из-за чего компания, которая и покупает, и
 * продаёт, теряла продавцовские кнопки.
 */

type Tile = {
  key: string;
  icon: typeof Receipt;
  label: string;
  caption: string;
  hash: string | null;
  count?: number;
};

/** Точечный переход к документу. `?open=<id>` читают страницы договоров и счетов. */
const openHash = (page: string, id: number | null) => (id ? `${page}?open=${id}` : page);

function NextStepBanner({ step, onGo }: { step: DealDocumentStep; onGo: () => void }) {
  const { t } = useTranslation();
  if (step.code === 'DONE') {
    return (
      <div className="flex items-center gap-2 rounded-md border border-success/30 bg-success/5 px-3 py-2">
        <p className="text-sm text-muted-foreground">{t('dealChain.steps.DONE.done')}</p>
      </div>
    );
  }
  // Шаг за контрагентом — сообщаем об ожидании и НЕ показываем кнопку действия.
  if (!step.for_viewer) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2">
        <p className="text-sm text-muted-foreground">{t(`dealChain.steps.${step.code}.waiting`)}</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-sm font-medium">{t(`dealChain.steps.${step.code}.title`)}</p>
      <Button size="sm" className="shrink-0 gap-1.5" onClick={onGo}>
        {t(`dealChain.steps.${step.code}.action`)}
        <ArrowRight className="h-4 w-4" aria-hidden="true" />
      </Button>
    </div>
  );
}

function ChainTile({ tile }: { tile: Tile }) {
  const Icon = tile.icon;
  const go = () => { if (tile.hash) window.location.hash = tile.hash; };
  return (
    <button
      type="button"
      onClick={go}
      disabled={!tile.hash}
      aria-label={`${tile.label}: ${tile.caption}`}
      className="flex items-center gap-3 rounded-md border border-border p-3 text-left transition-colors hover:bg-accent disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent"
    >
      <Icon className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 truncate text-sm font-medium">
          {tile.label}
          {typeof tile.count === 'number' && tile.count > 1 && (
            <Badge variant="secondary">{tile.count}</Badge>
          )}
        </p>
        <p className="truncate text-xs text-muted-foreground">{tile.caption}</p>
      </div>
    </button>
  );
}

/**
 * Подпись статуса документа — по КОДУ, а не по имени, пришедшему с сервера.
 *
 * `deal_documents` отдаёт и `status` (код), и `status_name` (имя справочника, всегда русское).
 * Цепочка печатала имя, и в английском интерфейсе на карточке сделки стояло
 * «CT-2026-00004 · Подписан сторонами», «INV-… · Оплачен», «Принято клиентом» (проход глазами
 * 03-08). Канон ARCH-05 «по проводам коды, слова на краях» — тот же, что закрыл ленты событий.
 *
 * Имя остаётся ЗАПАСНЫМ путём: оператор может завести свой статус через Unfold, и словаря на
 * него не будет — тогда честнее показать имя из справочника, чем пустоту.
 */
function statusCaption(
  t: (key: string, opts?: Record<string, unknown>) => string,
  i18n: { exists: (key: string) => boolean },
  type: string,
  code?: string | null,
  name?: string | null,
): string {
  const key = documentStatusLabelKey(type, code);
  if (key && i18n.exists(key)) return t(key);
  return name ?? code ?? '';
}

function buildTiles(
  hub: DealDocumentHub,
  t: (key: string, opts?: Record<string, unknown>) => string,
  money: (v: string) => string,
  i18n: { exists: (key: string) => boolean },
): Tile[] {
  const tiles: Tile[] = [];

  tiles.push({
    key: 'contract',
    icon: FileSignature,
    label: t('dealChain.tiles.contract'),
    caption: hub.contract
      ? `${hub.contract.number} · ${statusCaption(t, i18n, 'contract', hub.contract.status, hub.contract.status_name)}`
      : t('dealChain.tiles.none'),
    hash: hub.contract ? openHash('contracts', hub.contract.id) : null,
  });

  const openInvoice = hub.invoices[0] ?? null;
  tiles.push({
    key: 'invoices',
    icon: Receipt,
    label: t('dealChain.tiles.invoices'),
    caption: openInvoice
      ? `${openInvoice.number} · ${statusCaption(t, i18n, 'invoice', openInvoice.status, openInvoice.status_name)}`
      : t('dealChain.tiles.none'),
    hash: openInvoice ? openHash('invoices', openInvoice.id) : null,
    count: hub.invoices.length,
  });

  tiles.push({
    key: 'payments',
    icon: HandCoins,
    label: t('dealChain.tiles.payments'),
    caption: hub.payments_count
      ? t('dealChain.tiles.paidTotal', { amount: money(hub.payments_total) })
      : t('dealChain.tiles.noPayments'),
    hash: hub.payments_count ? 'payments' : null,
    count: hub.payments_count,
  });

  const act = hub.acts[0] ?? null;
  tiles.push({
    key: 'acts',
    icon: ScrollText,
    label: t('dealChain.tiles.acts'),
    caption: act
      ? `${act.number} · ${statusCaption(t, i18n, 'act', act.status, act.status_name)}`
      : t('dealChain.tiles.none'),
    hash: act ? 'acts' : null,
    count: hub.acts.length,
  });

  tiles.push({
    key: 'fulfillment',
    icon: Truck,
    label: t('dealChain.tiles.fulfillment'),
    caption: hub.fulfillment
      ? statusCaption(t, i18n, 'fulfillment', hub.fulfillment.status, hub.fulfillment.status_name)
      : t('dealChain.tiles.none'),
    hash: hub.fulfillment ? 'fulfillments' : null,
  });

  return tiles;
}

export function DealChainCard({ dealId }: { dealId: number }) {
  const { t, i18n } = useTranslation();
  const { data: hub, isLoading } = useDealDocuments(dealId);
  const format = useCurrencyStore((state) => state.format);

  // До появления договора цепочки ещё нет — блок молчит, а не показывает пять пустых плиток.
  if (isLoading || !hub || (!hub.contract && hub.invoices.length === 0 && !hub.fulfillment)) return null;

  const money = (value: string) => format(Number(value));
  const tiles = buildTiles(hub, t, money, i18n);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <ScrollText className="h-4 w-4" aria-hidden="true" />
          {t('dealChain.title')}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {hub.next_step && (
          <NextStepBanner
            step={hub.next_step}
            onGo={() => {
              window.location.hash = openHash(hub.next_step!.page, hub.next_step!.object_id);
            }}
          />
        )}
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {tiles.map((tile) => <ChainTile key={tile.key} tile={tile} />)}
        </div>
      </CardContent>
    </Card>
  );
}

export default DealChainCard;
