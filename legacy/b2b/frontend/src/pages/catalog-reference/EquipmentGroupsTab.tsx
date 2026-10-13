import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Layers, Package } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useEquipmentGroups } from '@/hooks/useCatalog';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import type { EquipmentGroup } from '@/api/catalogApi';
import { LoadingRows, EmptyState, ErrorState } from '../shared/PageShell';
import { ReferenceProductsSheet, type ReferenceTarget } from './ReferenceProductsSheet';

/**
 * Группы оборудования (R6): плитки справочника, которые наконец ведут в товары (D8).
 *
 * До волны карточка группы несла `cursor-pointer`, ховер и шеврон «>» без единого
 * обработчика — интерфейс обещал переход, которого не было. Теперь плитка — настоящая
 * кнопка: клавиатурой тоже (role/tabIndex/Enter/Space), как у KPI-плиток `PageShell`.
 *
 * Поиск серверный (`?search=` у `EquipmentGroupViewSet`): справочник ж/д узлов вырастает до
 * сотен строк, и листать их плитками нежизнеспособно.
 */
export function EquipmentGroupsTab() {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search, 300);
  const { data: groups, isLoading, isError, refetch } = useEquipmentGroups(debouncedSearch || undefined);
  const [target, setTarget] = useState<ReferenceTarget | null>(null);

  const open = (group: EquipmentGroup) =>
    setTarget({ title: group.full_path || group.name, params: { equipment_groups: group.id } });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">{t('catalogReference.groups.hint')}</p>
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t('catalogReference.groups.searchPlaceholder')}
          className="w-full sm:w-64"
        />
      </div>

      {isLoading ? (
        <LoadingRows rows={4} />
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : !groups?.length ? (
        <EmptyState
          icon={<Layers className="h-5 w-5" />}
          message={t('pages.common.noData')}
          hint={t('catalogReference.groups.emptyHint')}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {groups.map((group: EquipmentGroup) => (
            <Card
              key={group.id}
              role="button"
              tabIndex={0}
              onClick={() => open(group)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  open(group);
                }
              }}
              className="cursor-pointer transition-colors hover:bg-muted/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <CardContent className="p-6">
                <div className="mb-4 flex items-start justify-between">
                  <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Layers className="h-6 w-6" aria-hidden="true" />
                  </div>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Package className="h-4 w-4" aria-hidden="true" />
                    {t('catalogReference.showProducts')}
                  </span>
                </div>
                <h3 className="mb-1 text-lg font-semibold">{group.name}</h3>
                {group.full_path && group.full_path !== group.name && (
                  <p className="text-xs text-muted-foreground">{group.full_path}</p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {target && <ReferenceProductsSheet target={target} onClose={() => setTarget(null)} />}
    </div>
  );
}

export default EquipmentGroupsTab;
