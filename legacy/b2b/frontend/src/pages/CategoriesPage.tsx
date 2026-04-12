import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Tags, ChevronDown } from 'lucide-react';
import { useCategories } from '@/hooks/useCatalog';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import type { Category } from '@/api/catalogApi';

export function CategoriesPage() {
  const { t } = useTranslation();
  const { data: categories, isLoading } = useCategories();

  const topLevel = (categories ?? []).filter((c: Category) => !c.parent);
  const getChildren = (parentId: number) => (categories ?? []).filter((c: Category) => c.parent === parentId);

  return (
    <PageShell
      title={t('pages.categories.title')}
      description={t('pages.categories.description')}
      icon={<Tags className="h-5 w-5" />}
    >
      {isLoading ? <LoadingRows rows={4} /> : topLevel.length === 0 ? (
        <EmptyState icon={<Tags className="h-5 w-5" />} message={t('pages.common.noData')} />
      ) : (
        <div className="space-y-2">
          {topLevel.map((cat: Category, idx: number) => {
            const children = getChildren(cat.id);
            return (
              <Collapsible key={cat.id} defaultOpen={idx === 0}>
                <Card className="border">
                  <CardContent className="p-0">
                    <CollapsibleTrigger asChild>
                      <Button variant="ghost" className="w-full p-4 flex items-center justify-between hover:bg-muted/50 transition-colors h-auto">
                        <div className="flex items-center gap-2">
                          <ChevronDown className="h-4 w-4 transition-transform" />
                          <span className="font-medium">{cat.name}</span>
                        </div>
                        <Badge variant="outline" className="text-xs">{children.length} {t('pages.common.items')}</Badge>
                      </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="border-t bg-muted/30 p-4">
                        {children.length === 0 ? (
                          <p className="text-xs text-muted-foreground ml-4">{t('pages.common.noData')}</p>
                        ) : (
                          <div className="flex flex-wrap gap-2 ml-4">
                            {children.map((child: Category) => (
                              <Badge key={child.id} variant="secondary" className="text-xs">{child.name}</Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    </CollapsibleContent>
                  </CardContent>
                </Card>
              </Collapsible>
            );
          })}
        </div>
      )}
    </PageShell>
  );
}

export default CategoriesPage;
