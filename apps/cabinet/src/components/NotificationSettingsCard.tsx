import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Bell, Check, Shield, AlertCircle } from 'lucide-react';
import { toast } from '@/lib/toast';

import { useNotificationSettings, useUpdateNotificationSettings } from '@/api/queries';
import type { NotificationGroupSettingsMap, NotificationChannelSettings } from '@/api/portal';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { ToneBadge } from '@/components/StatusBadge';
import { apiErrorKey } from '@/api/errors';
import { useMe } from '@/session/useMe';

type GroupKey = keyof NotificationGroupSettingsMap;

export function NotificationSettingsCard() {
  const { t } = useTranslation();
  const me = useMe().data;
  const isPartner = me?.roles?.includes('partner') ?? false;

  const { data, isPending, isError, error } = useNotificationSettings();
  const updateSettings = useUpdateNotificationSettings();

  const [overrides, setOverrides] = useState<Partial<Record<GroupKey, Partial<NotificationChannelSettings>>>>({});

  const localGroups = useMemo(() => {
    if (!data?.groups) return null;
    const merged = { ...data.groups };
    for (const [key, groupOverride] of Object.entries(overrides)) {
      const gKey = key as GroupKey;
      if (merged[gKey] && groupOverride) {
        merged[gKey] = { ...merged[gKey], ...groupOverride };
      }
    }
    return merged;
  }, [data, overrides]);

  const handleToggle = (group: GroupKey, channel: 'email' | 'telegram', checked: boolean) => {
    if (!localGroups) return;
    const current = localGroups[group];
    if (!current || current.required) return;

    setOverrides((prev) => ({
      ...prev,
      [group]: {
        ...(prev[group] || {}),
        [channel]: checked,
      },
    }));

    updateSettings.mutate(
      {
        groups: {
          [group]: {
            [channel]: checked,
          },
        },
      },
      {
        onSuccess: () => {
          setOverrides({});
          toast.success(t('profile.notifications.saved', 'Настройки уведомлений обновлены'));
        },
        onError: (err) => {
          setOverrides({});
          toast.error(t(apiErrorKey(err)));
        },
      },
    );
  };

  const groupKeys: GroupKey[] = [
    'documents',
    'money',
    'deliveries',
    'messages',
    ...(isPartner ? (['partner_products'] as GroupKey[]) : []),
    'security',
  ];

  return (
    <Card className="md:col-span-2" id="notification-settings-matrix">
      <CardHeader>
        <CardTitle>
          <h2 className="text-base flex items-center gap-2">
            <Bell className="size-4 text-primary" aria-hidden="true" />
            {t('profile.notifications.matrixTitle', 'Каналы уведомлений')}
          </h2>
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          {t('profile.notifications.matrixDesc', 'Выберите события и каналы, в которые хотите получать оповещения')}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {isPending ? (
          <p className="text-xs text-muted-foreground">{t('app.loading')}</p>
        ) : isError ? (
          <p className="text-xs text-destructive">{t(apiErrorKey(error))}</p>
        ) : !localGroups ? null : (
          <>
            {!data.telegram_connected && (
              <div className="flex items-start gap-2.5 p-3 rounded-xl bg-muted/60 border border-border/60 text-xs text-muted-foreground">
                <AlertCircle className="size-4 text-muted-foreground shrink-0 mt-0.5" aria-hidden="true" />
                <span>
                  {t(
                    'profile.notifications.telegramNotConnected',
                    'Telegram не подключён. Подключите бот выше, чтобы включить мгновенные уведомления в мессенджер.',
                  )}
                </span>
              </div>
            )}

            <div className="rounded-xl border border-border/60 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm border-collapse">
                  <thead>
                    <tr className="border-b border-border/60 bg-muted/40 text-xs text-muted-foreground">
                      <th className="p-3 font-medium">
                        {t('profile.notifications.colGroup', 'Категория событий')}
                      </th>
                      <th className="p-3 font-medium text-center w-28">
                        {t('profile.notifications.channelInApp', 'В кабинете')}
                      </th>
                      <th className="p-3 font-medium text-center w-28">
                        {t('profile.notifications.channelEmail', 'E-mail')}
                      </th>
                      <th className="p-3 font-medium text-center w-28">
                        {t('profile.notifications.channelTelegram', 'Telegram')}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    {groupKeys.map((group) => {
                      const item = localGroups[group];
                      if (!item) return null;

                      const isSecurity = group === 'security';

                      return (
                        <tr key={group} className="hover:bg-accent/30 transition-colors">
                          <td className="p-3">
                            <div className="flex flex-col gap-0.5">
                              <div className="font-medium flex items-center gap-1.5">
                                {isSecurity && <Shield className="size-3.5 text-primary" aria-hidden="true" />}
                                <span>{t(`profile.notifications.groups.${group}.title`, group)}</span>
                                {item.required && (
                                  <ToneBadge tone="warning" className="text-xs py-0 px-1.5">
                                    {t('profile.notifications.alwaysOn', 'Обязательно')}
                                  </ToneBadge>
                                )}
                              </div>
                              <span className="text-xs text-muted-foreground">
                                {t(`profile.notifications.groups.${group}.desc`, '')}
                              </span>
                            </div>
                          </td>

                          {/* В кабинете — всегда активно */}
                          <td className="p-3 text-center">
                            <div className="flex justify-center">
                              <div className="size-5 rounded-full bg-primary/10 text-primary flex items-center justify-center">
                                <Check className="size-3.5" aria-hidden="true" />
                              </div>
                            </div>
                          </td>

                          {/* Email */}
                          <td className="p-3 text-center">
                            <div className="flex justify-center">
                              <Checkbox
                                checked={item.email}
                                disabled={item.required || updateSettings.isPending}
                                onCheckedChange={(checked) => handleToggle(group, 'email', Boolean(checked))}
                                aria-label={`${t(`profile.notifications.groups.${group}.title`, group)} — E-mail`}
                              />
                            </div>
                          </td>

                          {/* Telegram */}
                          <td className="p-3 text-center">
                            <div className="flex justify-center">
                              <Checkbox
                                checked={item.telegram}
                                disabled={
                                  item.required ||
                                  !data.telegram_connected ||
                                  updateSettings.isPending
                                }
                                onCheckedChange={(checked) =>
                                  handleToggle(group, 'telegram', Boolean(checked))
                                }
                                aria-label={`${t(`profile.notifications.groups.${group}.title`, group)} — Telegram`}
                              />
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
