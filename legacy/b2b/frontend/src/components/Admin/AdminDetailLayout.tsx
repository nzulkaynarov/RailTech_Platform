import { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs';
import { ChevronLeft } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface AdminDetailBadge {
  label: ReactNode;
  variant?: 'default' | 'secondary' | 'destructive' | 'outline';
  className?: string;
}

export interface AdminDetailTab {
  id: string;
  label: ReactNode;
  content: ReactNode;
  /** Disabled tabs render as greyed out (e.g. files-before-save). */
  disabled?: boolean;
}

export interface AdminDetailLayoutProps {
  /** Called when the "back" control is used. */
  onBack?: () => void;
  backLabel?: ReactNode;
  /** Primary title in header. */
  title: ReactNode;
  subtitle?: ReactNode;
  /** Status badges shown next to the title. */
  badges?: AdminDetailBadge[];
  /** Quick action buttons in the header right area. Primary actions. */
  actions?: ReactNode;
  /** Default tab id. Falls back to the first tab. */
  defaultTab?: string;
  tabs: AdminDetailTab[];
  /** Optional left-aligned avatar/icon in the header. */
  leading?: ReactNode;
  /** Rendered as the last tab automatically — dangerous operations. */
  dangerZone?: ReactNode;
}

export function AdminDetailLayout(props: AdminDetailLayoutProps): React.ReactNode {
  const { t } = useTranslation();
  const {
    onBack,
    backLabel,
    title,
    subtitle,
    badges,
    actions,
    defaultTab,
    tabs,
    leading,
    dangerZone,
  } = props;

  const allTabs: AdminDetailTab[] = dangerZone
    ? [
        ...tabs,
        {
          id: 'danger',
          label: t('adminDetail.dangerZone'),
          content: dangerZone,
        },
      ]
    : tabs;

  const firstTabId = defaultTab ?? allTabs[0]?.id ?? '';

  return (
    <div className="flex flex-col gap-4">
      {onBack ? (
        <div className="flex items-center text-xs text-muted-foreground">
          <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={onBack}>
            <ChevronLeft className="h-3.5 w-3.5" />
            {backLabel ?? t('common.back')}
          </Button>
        </div>
      ) : null}

      <Card className="p-4 md:p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            {leading}
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-lg font-semibold">{title}</h1>
                {badges?.map((b, i) => (
                  <Badge
                    key={i}
                    variant={b.variant ?? 'secondary'}
                    className={cn('text-[10px]', b.className)}
                  >
                    {b.label}
                  </Badge>
                ))}
              </div>
              {subtitle ? (
                <div className="mt-1 text-xs text-muted-foreground">{subtitle}</div>
              ) : null}
            </div>
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      </Card>

      <Tabs defaultValue={firstTabId} className="flex flex-col gap-3">
        <TabsList className="h-9 overflow-x-auto">
          {allTabs.map((tab) => (
            <TabsTrigger
              key={tab.id}
              value={tab.id}
              disabled={tab.disabled}
              className={cn(
                'text-xs',
                tab.id === 'danger' && 'data-[state=active]:text-destructive',
              )}
            >
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {allTabs.map((tab) => (
          <TabsContent key={tab.id} value={tab.id} className="mt-0">
            {tab.content}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
