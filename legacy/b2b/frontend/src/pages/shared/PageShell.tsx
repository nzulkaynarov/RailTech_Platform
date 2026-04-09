import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';

interface PageShellProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  stats?: { label: string; value: string }[];
  actions?: { label: string; variant?: 'default' | 'outline'; onClick?: () => void }[];
  children?: React.ReactNode;
}

export function PageShell({ title, description, icon, stats, actions, children }: PageShellProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">{icon}</div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        {actions && (
          <div className="flex gap-2">
            {actions.map((a, i) => (
              <Button key={i} variant={a.variant ?? 'default'} onClick={a.onClick}>{a.label}</Button>
            ))}
          </div>
        )}
      </div>
      {stats && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {stats.map((s) => (
            <Card key={s.label} className="py-4 gap-1">
              <CardContent className="px-4">
                <p className="text-xs text-muted-foreground">{s.label}</p>
                <p className="text-2xl font-bold tabular-nums">{s.value}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      {children ?? (
        <Card>
          <CardContent className="flex h-64 items-center justify-center">
            <div className="text-center text-muted-foreground">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">{icon}</div>
              <p className="text-sm font-medium">{t('pages.common.sectionInDevelopment')}</p>
              <p className="mt-1 text-xs">{t('pages.common.comingSoon')}</p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ icon, message }: { icon: React.ReactNode; message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">{icon}</div>
      <p className="text-sm font-medium">{message}</p>
    </div>
  );
}
