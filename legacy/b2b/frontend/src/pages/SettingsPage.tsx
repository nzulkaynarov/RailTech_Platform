import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Globe, Palette, Store, Building2, ShieldCheck } from 'lucide-react';

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

import { useAuthStore } from '@/store/authStore';
import { useUserStore, companyStatusLabels } from '@/store/userStore';
import { useThemeStore } from '@/store/themeStore';
import { useSystemSettings, useUpdateSystemSettings } from '@/hooks/useSystemSettings';
import { CompanyTeamSettings } from '@/components/Cabinet/CompanyTeamSettings';
import { ChargeTemplatesSettings } from '@/components/Cabinet/ChargeTemplatesSettings';
import { CompanyDocumentProfileSettings } from '@/components/Cabinet/CompanyDocumentProfileSettings';
import { CompanyDefaultsSettings } from '@/components/Cabinet/CompanyDefaultsSettings';
import { CompanyNumberingSettings } from '@/components/Cabinet/CompanyNumberingSettings';

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
  const { role, company, capabilities } = useUserStore();
  const { theme, setTheme } = useThemeStore();
  const isOwner = useAuthStore((s) => s.user?.workspace_role === 'OWNER');
  const isAdmin = role === 'ADMIN';
  // ADR-0005 U2: gate the company-admin hub on the CompanyRole PERMISSION, not WorkspaceRole
  // OWNER + seller-context. This (a) lets a delegated «Администратор компании» (settings.edit /
  // charge_templates.manage) without the OWNER WorkspaceRole reach the hub the backend already
  // authorizes them for, and (b) stops a dual buyer+seller owner losing the hub in BUYER context.
  // Fallback to isOwner when permission data is absent (old /me payload); backend still enforces.
  const perms = capabilities.permissions;
  const canEditCompany = perms.length
    ? perms.includes('settings.edit') || perms.includes('charge_templates.manage')
    : isOwner;
  // Fake rows trimmed — currency/timezone/dateFormat/density/sidebar didn't
  // feed back into any consumer and made the panel feel like a mock. Only
  // Language (i18next) and Theme (themeStore) actually change the UI.

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t('settings.title')}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t('settings.subtitle')}</p>
      </div>

      <Tabs defaultValue="general">
        <TabsList>
          <TabsTrigger value="general">{t('settings.tabs.general')}</TabsTrigger>
          {/* Company-Admin hub — company business config (defaults, numbering, templates,
              document profile). Gated on the settings.edit / charge_templates.manage PERMISSION. */}
          {!isAdmin && canEditCompany && (
            <TabsTrigger value="companyAdmin">{t('settings.tabs.companyAdmin')}</TabsTrigger>
          )}
          {/* Workspace members manage their team here; the OWNER also gets the
              invite form (gated inside CompanyTeamSettings). Hidden for Platform Admin. */}
          {!isAdmin && <TabsTrigger value="team">{t('settings.tabs.team')}</TabsTrigger>}
          {isAdmin && <TabsTrigger value="company">{t('settings.tabs.company')}</TabsTrigger>}
          {isAdmin && <TabsTrigger value="platform">{t('settings.tabs.platform')}</TabsTrigger>}
        </TabsList>

        {/* General — language + theme, both actually wired. */}
        <TabsContent value="general" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('settings.general.title')}</CardTitle>
              <CardDescription>{t('settings.general.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <SettingRow icon={Globe} title={t('settings.general.language')} description={t('settings.general.languageDesc')}>
                <Select value={i18n.language?.startsWith('ru') ? 'ru' : 'en'} onValueChange={(val) => i18n.changeLanguage(val)}>
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ru">{t('settings.general.langRu')}</SelectItem>
                    <SelectItem value="en">{t('settings.general.langEn')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>

              <SettingRow icon={Palette} title={t('settings.appearance.theme')} description={t('settings.appearance.themeDesc')}>
                <Select value={theme} onValueChange={(val) => setTheme(val as 'light' | 'dark')}>
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="light">{t('settings.appearance.themeLight')}</SelectItem>
                    <SelectItem value="dark">{t('settings.appearance.themeDark')}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Company-Admin hub — one coherent place for the company's КП defaults, document
            numbering, charge templates and document profile. Gated on settings.edit /
            charge_templates.manage (U2), not WorkspaceRole — so a delegated company admin sees it. */}
        {!isAdmin && canEditCompany && (
          <TabsContent value="companyAdmin" className="space-y-4">
            <CompanyAdminHub />
          </TabsContent>
        )}

        {/* Team — invite/manage company members (OWNER) or view team (members) */}
        {!isAdmin && (
          <TabsContent value="team" className="space-y-4">
            <CompanyTeamSettings />
          </TabsContent>
        )}

        {/* Platform (Admin only) — full SystemSettings CRUD */}
        {isAdmin && (
          <TabsContent value="platform" className="space-y-4">
            <PlatformSettings />
          </TabsContent>
        )}

        {/* Company context (Admin only) — read-only preview */}
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
                    {company.statusEntries.length === 0
                      ? <span className="text-xs text-muted-foreground">—</span>
                      : company.statusEntries.map((entry) => (
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

/**
 * Seller Company-Admin hub — consolidates the company's business config (КП defaults,
 * document numbering, charge templates, document profile) under one tab with a nested
 * sub-navigation. Each sub-section is wired to its own OWNER-gated endpoint.
 */
function CompanyAdminHub() {
  const { t } = useTranslation();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('settings.companyAdmin.title')}</CardTitle>
        <CardDescription>{t('settings.companyAdmin.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="documentProfile" className="w-full">
          <TabsList className="flex-wrap">
            <TabsTrigger value="documentProfile">{t('settings.tabs.documentProfile')}</TabsTrigger>
            <TabsTrigger value="defaults">{t('settings.tabs.defaults')}</TabsTrigger>
            <TabsTrigger value="numbering">{t('settings.tabs.numbering')}</TabsTrigger>
            <TabsTrigger value="templates">{t('settings.tabs.templates')}</TabsTrigger>
          </TabsList>

          <TabsContent value="documentProfile" className="mt-4">
            <CompanyDocumentProfileSettings />
          </TabsContent>
          <TabsContent value="defaults" className="mt-4">
            <CompanyDefaultsSettings />
          </TabsContent>
          <TabsContent value="numbering" className="mt-4">
            <CompanyNumberingSettings />
          </TabsContent>
          <TabsContent value="templates" className="mt-4">
            <ChargeTemplatesSettings />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
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
