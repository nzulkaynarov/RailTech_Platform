import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Loader2, Package, Save } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { useProduct } from '@/hooks/useCatalog';
import { useAuthStore } from '@/store/authStore';
import { productStatusLabelKey } from '@/lib/codes';

import { useProductForm } from '@/components/Shared/product-form/useProductForm';
import { CompletenessRail } from './CompletenessRail';
import { AiPanelSection } from './AiPanelSection';
import { BasicsSection } from './BasicsSection';
import { ClassificationSection } from './ClassificationSection';
import { SpecificationsSection } from './SpecificationsSection';
import { MediaSection } from './MediaSection';
import { CommerceSection } from './CommerceSection';
import { ActionsSection } from './ActionsSection';
import { SECTION_IDS, scrollToSection } from './anchors';

const STATUS_BADGE_VARIANT: Record<string, 'success' | 'warning' | 'neutral'> = {
  PUBLISHED: 'success',
  DRAFT: 'warning',
  ARCHIVED: 'neutral',
};

/**
 * Карточка товара = СТРАНИЦА, а не шторка (волна R3; D4, D9, D15, D16, D17).
 *
 * Эталон — Akeneo / Amazon Seller Central: полноэкранная карточка с секциями и
 * индикатором полноты ВНУТРИ, каждый недостающий пункт — якорь к своей секции.
 * Логика формы (черновик, оффер, ИИ-предложения, сохранение) — тот же
 * `useProductForm`, что у операторской шторки: одна форма — одно поведение.
 *
 * `productId` нет — режим создания: первый «Сохранить черновик» (достаточно имени)
 * создаёт карточку, страница ОСТАЁТСЯ на месте и открывает загрузку медиа (D17).
 */
export function ProductEditorPage({
  productId, onNavigate,
}: {
  productId?: string;
  onNavigate: (page: string) => void;
}) {
  const { t } = useTranslation();
  const sellerCompanyId = useAuthStore((state) => state.user?.company?.id);
  // id, полученный первым сохранением в режиме создания, — дальше страница живёт как редактор.
  const [createdId, setCreatedId] = useState<number | null>(null);
  const effectiveId = productId ?? (createdId !== null ? String(createdId) : undefined);
  const isCreate = !effectiveId;

  const { data: product, isLoading, error, refetch } = useProduct(effectiveId ?? '');

  const handleSaved = (savedId: number) => {
    if (effectiveId) return;
    setCreatedId(savedId);
    // Бесшовный первый шаг (D17): секция медиа отрисуется с пришедшим id — подводим к ней.
    window.setTimeout(() => scrollToSection(SECTION_IDS.media), 300);
  };

  const form = useProductForm({ target: product ?? null, sellerCompanyId, onSaved: handleSaved });

  if (effectiveId && isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-40" />
        <div className="flex flex-col gap-4 lg:flex-row">
          <Skeleton className="h-48 w-full lg:w-64" />
          <div className="flex-1 space-y-4">
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        </div>
      </div>
    );
  }

  if (effectiveId && (error || !product)) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3">
        <Package className="size-12 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          {error ? t('common.loadError') : t('catalog.productNotFound')}
        </p>
        <div className="flex gap-2">
          {error && (
            <Button variant="outline" onClick={() => refetch()}>{t('common.retry')}</Button>
          )}
          <Button variant="ghost" onClick={() => onNavigate('nomenclature')}>{t('common.back')}</Button>
        </div>
      </div>
    );
  }

  const statusKey = productStatusLabelKey(product?.status_code);

  return (
    <div className="flex flex-col gap-4">
      <Button
        variant="ghost"
        className="-ml-2 w-fit gap-2"
        onClick={() => onNavigate('nomenclature')}
      >
        <ArrowLeft className="size-4" aria-hidden="true" />
        {t('common.backToList')}
      </Button>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <h1 className="min-w-0 truncate text-lg font-bold tracking-tight">
            {isCreate ? t('productEditor.titleNew') : (product?.name || t('productEditor.titleNew'))}
          </h1>
          {!isCreate && statusKey && (
            <StatusBadge
              label={t(statusKey)}
              variant={STATUS_BADGE_VARIANT[product?.status_code ?? ''] ?? 'neutral'}
            />
          )}
        </div>
        <Button className="gap-1.5" disabled={form.busy} onClick={form.submit}>
          {form.busy
            ? <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            : <Save className="size-4" aria-hidden="true" />}
          {isCreate ? t('productEditor.saveDraft') : t('adminCatalog.save')}
        </Button>
      </div>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        {/* Узкая рейка полноты — на десктопе слева и липкая, на мобиле над секциями. */}
        <CompletenessRail
          completeness={product?.completeness}
          isCreate={isCreate}
          className="w-full lg:sticky lg:top-6 lg:w-64 lg:shrink-0"
        />
        <div className="min-w-0 flex-1 space-y-4">
          <AiPanelSection form={form} />
          <BasicsSection form={form} />
          <ClassificationSection form={form} />
          <SpecificationsSection form={form} />
          <MediaSection productId={product?.id ?? createdId} />
          {form.sellerMode && <CommerceSection form={form} />}
          {product && <ActionsSection product={product} />}
        </div>
      </div>
    </div>
  );
}
