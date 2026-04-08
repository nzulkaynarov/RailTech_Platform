import { useTranslation } from 'react-i18next';
import {
  Globe, Palette, Bell, Shield, Database, Plug, Users, Building2, FileText, Monitor,
  Factory, Store,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { useUserStore, companyStatusLabels } from '@/store/userStore';
import { useThemeStore } from '@/store/themeStore';

function SettingRow({ icon: Icon, title, description, children }: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border p-4">
      <div className="flex items-center gap-3">
        <Icon className="h-5 w-5 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium">{title}</p>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </div>
      {children}
    </div>
  );
}

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { role, activeStatus, company } = useUserStore();
  const { theme, setTheme } = useThemeStore();
  const isAdmin = role === 'ADMIN';
  const isManagerOrAdmin = role === 'ADMIN' || role === 'MANAGER';

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t('settings.title')}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t('settings.subtitle')}</p>
      </div>

      <Tabs defaultValue="general">
        <TabsList>
          <TabsTrigger value="general">{t('settings.tabs.general')}</TabsTrigger>
          <TabsTrigger value="appearance">{t('settings.tabs.appearance')}</TabsTrigger>
          {isManagerOrAdmin && (activeStatus === 'SELLER' || activeStatus === 'MANUFACTURER') && (
            <TabsTrigger value="business">{t('settings.tabs.business')}</TabsTrigger>
          )}
          {isAdmin && <TabsTrigger value="company">{t('settings.tabs.company')}</TabsTrigger>}
          {isAdmin && <TabsTrigger value="system">{t('settings.tabs.system')}</TabsTrigger>}
        </TabsList>

        {/* General */}
        <TabsContent value="general" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('settings.general.title')}</CardTitle>
              <CardDescription>{t('settings.general.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <SettingRow icon={Globe} title={t('settings.general.language')} description={t('settings.general.languageDesc')}>
                <Select value={i18n.language?.startsWith('ru') ? 'ru' : i18n.language?.startsWith('en') ? 'en' : 'ru'} onValueChange={(val) => i18n.changeLanguage(val)}>
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ru">Русский</SelectItem>
                    <SelectItem value="en">English</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow icon={Database} title={t('settings.general.currency')} description={t('settings.general.currencyDesc')}>
                <Select defaultValue="usd">
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="usd">USD ($)</SelectItem>
                    <SelectItem value="uzs">{t('settings.general.currencyUZS')}</SelectItem>
                    <SelectItem value="eur">EUR</SelectItem>
                    <SelectItem value="rub">{t('settings.general.currencyRUB')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow icon={Globe} title={t('settings.general.timezone')} description={t('settings.general.timezoneDesc')}>
                <Select defaultValue="tashkent">
                  <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="tashkent">{t('settings.general.tzTashkent')}</SelectItem>
                    <SelectItem value="moscow">{t('settings.general.tzMoscow')}</SelectItem>
                    <SelectItem value="almaty">{t('settings.general.tzAlmaty')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow icon={FileText} title={t('settings.general.dateFormat')} description={t('settings.general.dateFormatDesc')}>
                <Select defaultValue="dmy">
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="dmy">{t('settings.general.dateDMY')}</SelectItem>
                    <SelectItem value="mdy">{t('settings.general.dateMDY')}</SelectItem>
                    <SelectItem value="ymd">{t('settings.general.dateYMD')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Appearance */}
        <TabsContent value="appearance" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('settings.appearance.title')}</CardTitle>
              <CardDescription>{t('settings.appearance.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <SettingRow icon={Palette} title={t('settings.appearance.theme')} description={t('settings.appearance.themeDesc')}>
                <Select value={theme} onValueChange={(val) => setTheme(val as 'light' | 'dark')}>
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="light">{t('settings.appearance.themeLight')}</SelectItem>
                    <SelectItem value="dark">{t('settings.appearance.themeDark')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow icon={Monitor} title={t('settings.appearance.density')} description={t('settings.appearance.densityDesc')}>
                <Select defaultValue="normal">
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="compact">{t('settings.appearance.densityCompact')}</SelectItem>
                    <SelectItem value="normal">{t('settings.appearance.densityNormal')}</SelectItem>
                    <SelectItem value="comfortable">{t('settings.appearance.densityComfortable')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow icon={Monitor} title={t('settings.appearance.sidebar')} description={t('settings.appearance.sidebarDesc')}>
                <Select defaultValue="expanded">
                  <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="expanded">{t('settings.appearance.sidebarExpanded')}</SelectItem>
                    <SelectItem value="collapsed">{t('settings.appearance.sidebarCollapsed')}</SelectItem>
                    <SelectItem value="hover">{t('settings.appearance.sidebarHover')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Business Settings (Seller/Manufacturer, Manager+) */}
        {isManagerOrAdmin && (activeStatus === 'SELLER' || activeStatus === 'MANUFACTURER') && (
          <TabsContent value="business" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  {activeStatus === 'SELLER' ? t('settings.business.sellerTitle') : t('settings.business.manufacturerTitle')}
                </CardTitle>
                <CardDescription>
                  {activeStatus === 'SELLER'
                    ? t('settings.business.sellerDescription')
                    : t('settings.business.manufacturerDescription')
                  }
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {activeStatus === 'SELLER' && (
                  <>
                    <SettingRow icon={FileText} title={t('settings.business.autoNumbering')} description={t('settings.business.autoNumberingDesc')}>
                      <Switch defaultChecked />
                    </SettingRow>
                    <SettingRow icon={Bell} title={t('settings.business.reminders')} description={t('settings.business.remindersDesc')}>
                      <Switch defaultChecked />
                    </SettingRow>
                    <SettingRow icon={Database} title={t('settings.business.defaultMargin')} description={t('settings.business.defaultMarginDesc')}>
                      <Select defaultValue="15">
                        <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="10">10%</SelectItem>
                          <SelectItem value="15">15%</SelectItem>
                          <SelectItem value="20">20%</SelectItem>
                          <SelectItem value="25">25%</SelectItem>
                        </SelectContent>
                      </Select>
                    </SettingRow>
                    <SettingRow icon={Database} title={t('settings.business.vat')} description={t('settings.business.vatDesc')}>
                      <Select defaultValue="12">
                        <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="12">12%</SelectItem>
                          <SelectItem value="0">{t('settings.business.vatExport')}</SelectItem>
                        </SelectContent>
                      </Select>
                    </SettingRow>
                  </>
                )}
                {activeStatus === 'MANUFACTURER' && (
                  <>
                    <SettingRow icon={Factory} title={t('settings.business.orderMode')} description={t('settings.business.orderModeDesc')}>
                      <Select defaultValue="manual">
                        <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="auto">{t('settings.business.orderModeAuto')}</SelectItem>
                          <SelectItem value="manual">{t('settings.business.orderModeManual')}</SelectItem>
                        </SelectContent>
                      </Select>
                    </SettingRow>
                    <SettingRow icon={Bell} title={t('settings.business.orderNotifications')} description={t('settings.business.orderNotificationsDesc')}>
                      <Switch defaultChecked />
                    </SettingRow>
                    <SettingRow icon={Database} title={t('settings.business.minOrder')} description={t('settings.business.minOrderDesc')}>
                      <Select defaultValue="1000">
                        <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="0">{t('settings.business.noLimit')}</SelectItem>
                          <SelectItem value="500">$500</SelectItem>
                          <SelectItem value="1000">$1 000</SelectItem>
                          <SelectItem value="5000">$5 000</SelectItem>
                        </SelectContent>
                      </Select>
                    </SettingRow>
                    <SettingRow icon={Store} title={t('settings.business.partnerSuppliers')} description={t('settings.business.partnerSuppliersDesc')}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="outline" size="sm" disabled>{t('settings.business.manage')}</Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          {t('common.comingSoon')}
                        </TooltipContent>
                      </Tooltip>
                    </SettingRow>
                  </>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* Company (Admin only) */}
        {isAdmin && (
          <TabsContent value="company" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t('settings.company.title')}</CardTitle>
                <CardDescription>{t('settings.company.description')}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <SettingRow icon={Building2} title={t('settings.company.statuses')} description={t('settings.company.statusesDesc')}>
                  <div className="flex gap-1.5">
                    {company.statusEntries.map((entry) => (
                      <Badge key={entry.status} variant="secondary" className="text-xs">
                        {t(companyStatusLabels[entry.status])}
                        {entry.verification === 'pending' && ` (${t('settings.company.pending')})`}
                      </Badge>
                    ))}
                  </div>
                </SettingRow>
                <SettingRow icon={Users} title={t('settings.company.users')} description={t('settings.company.usersDesc')}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button size="sm" disabled>{t('settings.company.invite')}</Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t('common.comingSoon')}
                    </TooltipContent>
                  </Tooltip>
                </SettingRow>
                <SettingRow icon={Shield} title={t('settings.company.rolesPermissions')} description={t('settings.company.rolesPermissionsDesc')}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="sm" disabled>{t('settings.company.manage')}</Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t('common.comingSoon')}
                    </TooltipContent>
                  </Tooltip>
                </SettingRow>
                <SettingRow icon={Shield} title={t('settings.company.delegation')} description={t('settings.company.delegationDesc')}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="sm" disabled>{t('settings.company.configure')}</Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t('common.comingSoon')}
                    </TooltipContent>
                  </Tooltip>
                </SettingRow>
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* System (Admin only) */}
        {isAdmin && (
          <TabsContent value="system" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t('settings.system.title')}</CardTitle>
                <CardDescription>{t('settings.system.description')}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <SettingRow icon={Plug} title={t('settings.system.apiIntegrations')} description={t('settings.system.apiIntegrationsDesc')}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="sm" disabled>{t('settings.system.configure')}</Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t('common.comingSoon')}
                    </TooltipContent>
                  </Tooltip>
                </SettingRow>
                <SettingRow icon={Database} title={t('settings.system.backup')} description={t('settings.system.backupDesc')}>
                  <Switch defaultChecked />
                </SettingRow>
                <SettingRow icon={Shield} title={t('settings.system.passwordPolicy')} description={t('settings.system.passwordPolicyDesc')}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="sm" disabled>{t('settings.system.configure')}</Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t('common.comingSoon')}
                    </TooltipContent>
                  </Tooltip>
                </SettingRow>
                <SettingRow icon={FileText} title={t('settings.system.auditLogs')} description={t('settings.system.auditLogsDesc')}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="sm" disabled>{t('settings.system.view')}</Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t('common.comingSoon')}
                    </TooltipContent>
                  </Tooltip>
                </SettingRow>
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
