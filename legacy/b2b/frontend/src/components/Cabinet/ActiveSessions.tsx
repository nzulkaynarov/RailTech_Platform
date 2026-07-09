import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Monitor, Smartphone, LogOut } from 'lucide-react';
import { format } from 'date-fns';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { accountsApi } from '@/api/accountsApi';
import type { Session } from '@/api/accountsApi';
import { Skeleton } from '@/components/ui/skeleton';

export function ActiveSessions() {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState(false);

  const fetchSessions = async () => {
    try {
      setLoading(true);
      const data = await accountsApi.getActiveSessions();
      setSessions(data);
    } catch (e) {
      toast.error(t('profile.security.sessionsError'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  const handleRevokeAll = async () => {
    try {
      setRevoking(true);
      await accountsApi.revokeAllSessions();
      toast.success(t('profile.security.sessionsRevoked'));
      await fetchSessions();
    } catch (e) {
      toast.error(t('common.error'));
    } finally {
      setRevoking(false);
    }
  };

  if (loading) {
    return <div className="space-y-4"><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /></div>;
  }

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">{t('profile.security.activeSessions')}</CardTitle>
            <CardDescription>{t('profile.security.activeSessionsDesc')}</CardDescription>
          </div>
          {sessions.length > 1 && (
            <Button variant="destructive" size="sm" onClick={handleRevokeAll} disabled={revoking}>
              <LogOut className="w-4 h-4 mr-2" />
              {t('profile.security.revokeOtherSessions')}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {sessions.map((session, index) => {
          const isCurrent = session.is_current;
          const isMobile = session.user_agent?.toLowerCase().includes('mobile');
          const Icon = isMobile ? Smartphone : Monitor;
          
          return (
            <div key={session.id || index} className="flex items-start justify-between rounded-lg border p-4">
              <div className="flex items-start gap-4">
                <div className="p-2 bg-muted rounded-full">
                  <Icon className="w-5 h-5 text-muted-foreground" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-sm">
                      {session.ip_address || t('common.unknown')}
                    </p>
                    {isCurrent && <Badge variant="default" className="text-[10px] uppercase h-5">{t('profile.security.currentSession')}</Badge>}
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    {session.user_agent ? (
                      <span className="line-clamp-1">{session.user_agent}</span>
                    ) : (
                      t('common.unknownDevice')
                    )}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {t('profile.security.signedIn')}: {format(new Date(session.created_at), 'PPP p')}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
        {sessions.length === 0 && (
          <div className="text-center text-muted-foreground text-sm py-4">
            {t('common.noData')}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
