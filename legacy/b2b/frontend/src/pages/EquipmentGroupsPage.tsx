import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Layers, ChevronRight } from 'lucide-react';
import { useEquipmentGroups } from '@/hooks/useCatalog';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import type { EquipmentGroup } from '@/api/catalogApi';

export function EquipmentGroupsPage() {
  const { t } = useTranslation();
  const { data: groups, isLoading, isError, refetch } = useEquipmentGroups();

  return (
    <PageShell
      title={t('pages.equipmentGroups.title')}
      description={t('pages.equipmentGroups.description')}
      icon={<Layers className="h-5 w-5" />}
    >
      {isLoading ? <LoadingRows rows={4} /> : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : !groups?.length ? (
        <EmptyState icon={<Layers className="h-5 w-5" />} message={t('pages.common.noData')} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {groups.map((group: EquipmentGroup) => (
            <Card key={group.id} className="cursor-pointer hover:shadow-md transition-shadow">
              <CardContent className="p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Layers className="h-6 w-6" />
                  </div>
                  <ChevronRight className="h-5 w-5 text-muted-foreground" />
                </div>
                <h3 className="font-semibold text-lg mb-3">{group.name}</h3>
                {group.full_path && group.full_path !== group.name && (
                  <p className="text-xs text-muted-foreground">{t('pages.equipmentGroups.hasParent')}</p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </PageShell>
  );
}

export default EquipmentGroupsPage;
