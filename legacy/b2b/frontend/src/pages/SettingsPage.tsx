import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Globe, Palette, Bell, Database, FileText, Monitor,
  Factory, Store, Building2, ShieldCheck,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { useUserStore, companyStatusLabels } from '@/store/userStore';
import { useThemeStore } from '@/store/themeStore';
import { useSystemSettings, useUpdateSystemSettings } from '@/hooks/useSystemSettings';

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

  // Local preferences (localStorage)
  const [currency, setCurrency] = useState(() => localStorage.getItem('railtech-currency') || 'usd');
  const [timezone, setTimezone] = useState(() => localStorage.getItem('railtech-timezone') || 'tashkent');
  const [dateFormat, setDateFormat] = useState(() => localStorage.getItem('railtech-dateformat') || 'dmy');
  const [density, setDensity] = useState(() => localStorage.getItem('railtech-density') || 'normal');
  const [sidebarMode, setSidebarMode] = useState(() => localStorage.getItem('railtech-sidebar') || 'expanded');

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
          {isAdmin && <TabsTrigger value="platform">{t('settings.tabs.platform')}</TabsTrigger>}
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
                    <SelectItem value="ru">{t('settings.general.langRu')}</SelectItem>
                    <SelectItem value="en">{t('settings.general.langEn')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow icon={Database} title={t('settings.general.currency')} description={t('settings.general.currencyDesc')}>
                <Select
                  value={currency}
                  onValueChange={(val) => {
                    setCurrency(val);
                    localStorage.setItem('railtech-currency', val);
                  }}
                >
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="usd">{t('settings.general.currencyUSD')}</SelectItem>
                    <SelectItem value="uzs">{t('settings.general.currencyUZS')}</SelectItem>
                    <SelectItem value="eur">EUR</SelectItem>
                    <SelectItem value="rub">{t('settings.general.currencyRUB')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow icon={Globe} title={t('settings.general.timezone')} description={t('settings.general.timezoneDesc')}>
                <Select
                  value={timezone}
                  onValueChange={(val) => {
                    setTimezone(val);
                    localStorage.setItem('railtech-timezone', val);
                  }}
                >
                  <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="tashkent">{t('settings.general.tzTashkent')}</SelectItem>
                    <SelectItem value="moscow">{t('settings.general.tzMoscow')}</SelectItem>
                    <SelectItem value="almaty">{t('settings.general.tzAlmaty')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow icon={FileText} title={t('settings.general.dateFormat')} description={t('settings.general.dateFormatDesc')}>
                <Select
                  value={dateFormat}
                  onValueChange={(val) => {
                    setDateFormat(val);
                    localStorage.setItem('railtech-dateformat', val);
                  }}
                >
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
                <Select
                  value={density}
                  onValueChange={(val) => {
                    setDensity(val);
                    localStorage.setItem('railtech-density', val);
                  }}
                >
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="compact">{t('settings.appearance.densityCompact')}</SelectItem>
                    <SelectItem value="normal">{t('settings.appearance.densityNormal')}</SelectItem>
                    <SelectItem value="comfortable">{t('settings.appearance.densityComfortable')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow icon={Monitor} title={t('settings.appearance.sidebar')} description={t('settings.appearance.sidebarDesc')}>
                <Select
                  value={sidebarMode}
                  onValueChange={(val) => {
                    setSidebarMode(val);
                    localStorage.setItem('railtech-sidebar', val);
                  }}
                >
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
                          <SelectItem value="500">{t('settings.business.minOrderValue', { amount: '500' })}</SelectItem>
                          <SelectItem value="1000">{t('settings.business.minOrderValue', { amount: '1 000' })}</SelectItem>
                          <SelectItem value="5000">{t('settings.business.minOrderValue', { amount: '5 000' })}</SelectItem>
                        </SelectContent>
                      </Select>
                    </SettingRow>
                  </>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* Platform (Admin only) */}
        {isAdmin && (
          <TabsContent value="platform" className="space-y-4">
            <PlatformSettings />
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
                <SettingRow icon={Store} title={t('settings.company.companyInfo')} description={t('settings.company.companyInfoDesc')}>
                  <Badge variant="outline" className="text-xs">
                    {company.name || '—'}
                  </Badge>
                </SettingRow>
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}

function PlatformSettings() {
  const { t } = useTranslation();
  const { data, isLoading } = useSystemSettings();
  const updateMut = useUpdateSystemSettings();

  const [vatRate, setVatRate] = useState('');
  const [standardMargin, setStandardMargin] = useState('');
  const [exchangeRate, setExchangeRate] = useState('');
  const [platformName, setPlatformName] = useState('');
  const [maintenanceMode, setMaintenanceMode] = useState(false);
  const [twoFactor, setTwoFactor] = useState(false);

  useEffect(() => {
    if (data) {
      setVatRate(data.vat_rate ?? '');
      setStandardMargin(data.standard_margin ?? '');
      setExchangeRate(data.exchange_rate_usd_uzs ?? '');
      setPlatformName(data.platform_name ?? '');
      setMaintenanceMode(Boolean(data.maintenance_mode));
      setTwoFactor(Boolean(data.is_two_factor_required));
    }
  }, [data]);

  const handleSave = async () => {
    try {
      await updateMut.mutateAsync({
        vat_rate: vatRate,
        standard_margin: standardMargin,
        exchange_rate_usd_uzs: exchangeRate,
        platform_name: platformName,
        maintenance_mode: maintenanceMode,
        is_two_factor_required: twoFactor,
      });
      toast.success(t('settings.platform.saved'));
    } catch {
      toast.error(t('settings.platform.saveFailed'));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" />
          {t('settings.platform.title')}
        </CardTitle>
        <CardDescription>{t('settings.platform.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>{t('settings.platform.vatRate')}</Label>
                <Input type="number" step="0.01" value={vatRate} onChange={(e) => setVatRate(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.standardMargin')}</Label>
                <Input type="number" step="0.01" value={standardMargin} onChange={(e) => setStandardMargin(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.exchangeRate')}</Label>
                <Input type="number" step="0.0001" value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.platformName')}</Label>
                <Input value={platformName} onChange={(e) => setPlatformName(e.target.value)} />
              </div>
            </div>

            <div className="flex items-center justify-between rounded-lg border p-3">
              <div>
                <p className="text-sm font-medium">{t('settings.platform.maintenance')}</p>
                <p className="text-xs text-muted-foreground">{t('settings.platform.maintenanceDesc')}</p>
              </div>
              <Switch checked={maintenanceMode} onCheckedChange={setMaintenanceMode} />
            </div>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <div>
                <p className="text-sm font-medium">{t('settings.platform.twoFactor')}</p>
                <p className="text-xs text-muted-foreground">{t('settings.platform.twoFactorDesc')}</p>
              </div>
              <Switch checked={twoFactor} onCheckedChange={setTwoFactor} />
            </div>

            <Button onClick={handleSave} disabled={updateMut.isPending}>
              {t('settings.platform.save')}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
