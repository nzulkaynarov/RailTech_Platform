import { useTranslation } from 'react-i18next';
import { Library } from 'lucide-react';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useUrlState } from '@/hooks/useUrlState';
import { PageShell } from './shared/PageShell';
import { HSDirectorySection } from './HSDirectoryPage';
import { CategoriesTab } from './catalog-reference/CategoriesTab';

/** Вкладки справочников. Идентификатор живёт в URL — ссылкой можно поделиться. */
export type ReferenceTab = 'hs' | 'categories';

const TABS: readonly ReferenceTab[] = ['hs', 'categories'];

const isTab = (value: string): value is ReferenceTab => (TABS as readonly string[]).includes(value);

/**
 * Вкладка из ХЭША (`#catalog-reference?ref=categories`).
 *
 * `useUrlState` живёт в search-части URL, а уведомления и письма строят ссылку хэш-запросом
 * (`notifications.services.spa_link`) — не прочитав её, уведомление «категория заведена»
 * приводило бы человека на вкладку ТН ВЭД.
 */
function tabFromHash(): ReferenceTab | null {
  const query = window.location.hash.split('?')[1];
  const value = query ? new URLSearchParams(query).get('ref') : null;
  return value && isTab(value) ? value : null;
}

interface CatalogReferencePageProps {
  /** Вкладка по умолчанию — из маршрута. */
  defaultTab?: ReferenceTab;
}

/**
 * «Справочники» (R6, D14) — классификаторы платформы одной страницей.
 *
 * Раздел «Номенклатура» состоял из ШЕСТИ пунктов меню, три из которых были справочниками
 * (ТН ВЭД, категории, группы оборудования) — а слово «Номенклатура» означало в меню три
 * разные вещи. Эталон (Akeneo Settings, Shopify Settings, Odoo Configuration): справочники
 * живут ОДНИМ узлом с вкладками, а рабочие места — отдельно.
 *
 * Подпись честная: продавец справочниками не управляет (таксономию ведёт платформа —
 * решение владельца по вопросу 1 от 05-08), но может попросить категорию.
 */
export function CatalogReferencePage({ defaultTab = 'hs' }: CatalogReferencePageProps) {
  const { t } = useTranslation();
  const { get, set } = useUrlState();

  const fromSearch = get('ref');
  const active: ReferenceTab = isTab(fromSearch) ? fromSearch : tabFromHash() ?? defaultTab;

  return (
    <PageShell
      title={t('catalogReference.title')}
      description={t('catalogReference.description')}
      icon={<Library className="h-5 w-5" />}
    >
      <Tabs value={active} onValueChange={(value) => set({ ref: value })}>
        <TabsList>
          <TabsTrigger value="hs">{t('catalogReference.tabs.hs')}</TabsTrigger>
          <TabsTrigger value="categories">{t('catalogReference.tabs.categories')}</TabsTrigger>
        </TabsList>
        <TabsContent value="hs" className="mt-4">
          <HSDirectorySection />
        </TabsContent>
        <TabsContent value="categories" className="mt-4">
          <CategoriesTab />
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}

export default CatalogReferencePage;
