/**
 * Settings Hub (spec: Docs/dev/specs/settings-profile-redesign.md, PR 1) — единственный
 * хаб настроек: плоский список секций (buildSettingsSections, §2.2) в SettingsLayout
 * вместо «табов над табами». Контент секций монтируется как есть (редизайн — PR 2-4);
 * активная секция синхронизирована с `?section=` через useUrlState (deep-link + refresh).
 */
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Store, Building2 } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

import { useAuthStore } from '@/store/authStore';
import { useUserStore, companyStatusLabels } from '@/store/userStore';
import { useUrlState } from '@/hooks/useUrlState';
import {
  buildSettingsSections, defaultSettingsSection, type SettingsGateInput, type SettingsSectionKey,
} from '@/config/settingsSections';
import { SettingsLayout } from '@/components/Settings/SettingsLayout';
import { ProfileSection } from '@/components/Settings/ProfileSection';
import { SecuritySection } from '@/components/Settings/SecuritySection';
import { PlatformSettings } from '@/components/Settings/PlatformSettings';
import { CompanyTeamSettings } from '@/components/Cabinet/CompanyTeamSettings';
import { ChargeTemplatesSettings } from '@/components/Cabinet/ChargeTemplatesSettings';
import { CompanyDocumentProfileSettings } from '@/components/Cabinet/CompanyDocumentProfileSettings';
import { CompanyDefaultsSettings } from '@/components/Cabinet/CompanyDefaultsSettings';
import { CompanyNumberingSettings } from '@/components/Cabinet/CompanyNumberingSettings';
import { CompanyTab } from '@/components/Cabinet/CompanyTab';

export function SettingsPage() {
  const { t } = useTranslation();
  const { role, capabilities } = useUserStore();
  const isOwner = useAuthStore((s) => s.user?.workspace_role === 'OWNER');
  const isAdmin = role === 'ADMIN';
  const gate: SettingsGateInput = { isAdmin, isOwner, capabilities };
  const sections = buildSettingsSections(gate);

  // `?section=` живёт в search-части URL (useUrlState), hash остаётся `#settings` —
  // deep-link и refresh сохраняют секцию; невидимая/неизвестная секция → дефолт.
  const { get, set } = useUrlState();
  const urlSection = get('section');
  const activeSection: SettingsSectionKey = sections.some((section) => section.key === urlSection)
    ? (urlSection as SettingsSectionKey)
    : defaultSettingsSection(gate);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t('settings.title')}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t('settings.subtitle')}</p>
      </div>

      <SettingsLayout
        sections={sections.map((section) => ({ key: section.key, label: t(section.labelKey) }))}
        activeSection={activeSection}
        onSelectSection={(key) => set({ section: key })}
      >
        <SectionContent sectionKey={activeSection} isAdmin={isAdmin} />
      </SettingsLayout>
    </div>
  );
}

/** Маппинг секция → существующий компонент (монтируется как есть, spec PR 1). */
function SectionContent({ sectionKey, isAdmin }: { sectionKey: SettingsSectionKey; isAdmin: boolean }): ReactNode {
  switch (sectionKey) {
    case 'profile':
      return <ProfileSection />;
    case 'security':
      return <SecuritySection />;
    case 'company':
      // ADMIN — read-only превью (прежний admin-таб company); tenant — CompanyTab.
      return isAdmin ? <AdminCompanyPreview /> : <CompanyTab />;
    case 'documents':
      return <CompanyDocumentProfileSettings />;
    case 'defaults':
      return <CompanyDefaultsSettings />;
    case 'numbering':
      return <CompanyNumberingSettings />;
    case 'templates':
      return <ChargeTemplatesSettings />;
    case 'team':
      return <CompanyTeamSettings />;
    case 'platform':
      return <PlatformSettings />;
  }
}

/** Read-only превью компании для Platform Operator — перенесено из прежнего таба company как есть. */
function AdminCompanyPreview() {
  const { t } = useTranslation();
  const company = useUserStore((s) => s.company);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('settings.company.title')}</CardTitle>
        <CardDescription>{t('settings.company.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between rounded-lg border p-4">
          <div className="flex items-center gap-3">
            <Building2 className="h-5 w-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">{t('settings.company.statuses')}</p>
              <p className="text-xs text-muted-foreground">{t('settings.company.statusesDesc')}</p>
            </div>
          </div>
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
        </div>
        <div className="flex items-center justify-between rounded-lg border p-4">
          <div className="flex items-center gap-3">
            <Store className="h-5 w-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">{t('settings.company.companyInfo')}</p>
              <p className="text-xs text-muted-foreground">{t('settings.company.companyInfoDesc')}</p>
            </div>
          </div>
          <Badge variant="outline" className="text-xs">
            {company.name || '—'}
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
}
