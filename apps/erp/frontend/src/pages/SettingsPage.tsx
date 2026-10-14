/**
 * Settings Hub (spec: Docs/old/specs/settings-profile-redesign.md, PR 1) — единственный
 * хаб настроек: плоский список секций (buildSettingsSections, §2.2) в SettingsLayout
 * вместо «табов над табами». Контент секций монтируется как есть (редизайн — PR 2-4);
 * активная секция синхронизирована с `?section=` через useUrlState (deep-link + refresh).
 */
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/store/authStore';
import { useUserStore } from '@/store/userStore';
import { useUrlState } from '@/hooks/useUrlState';
import {
  buildSettingsSections, defaultSettingsSection, type SettingsGateInput, type SettingsSectionKey,
} from '@/config/settingsSections';
import { SettingsLayout } from '@/components/Settings/SettingsLayout';
import { ProfileSection } from '@/components/Settings/ProfileSection';
import { SecuritySection } from '@/components/Settings/SecuritySection';
import { PlatformSettings } from '@/components/Settings/PlatformSettings';
import { CompanyTeamSettings } from '@/components/Settings/team/CompanyTeamSettings';
import { ChargeTemplatesSettings } from '@/components/Cabinet/ChargeTemplatesSettings';
import { DocumentTemplatesSettings } from '@/components/Settings/DocumentTemplatesSettings';
import { CompanyDocumentProfileSettings } from '@/components/Cabinet/CompanyDocumentProfileSettings';
import { CompanyDefaultsSettings } from '@/components/Cabinet/CompanyDefaultsSettings';
import { CompanyNumberingSettings } from '@/components/Cabinet/CompanyNumberingSettings';
import { CompanyTab } from '@/components/Cabinet/CompanyTab';

export function SettingsPage() {
  const { t } = useTranslation();
  const capabilities = useUserStore((s) => s.capabilities);
  const isOwner = useAuthStore((s) => s.user?.workspace_role === 'OWNER');
  const gate: SettingsGateInput = { isOwner, capabilities };
  const sections = buildSettingsSections(gate);

  // `?section=` живёт в search-части URL (useUrlState), hash остаётся `#settings` —
  // deep-link и refresh сохраняют секцию; невидимая/неизвестная секция → дефолт.
  const { get, set } = useUrlState();
  // Старые deep-link `?section=documents` (когда-то = бланк+бренд) маппим на новую секцию
  // `branding` (PDF-бланк/бренд теперь отдельная секция в группе «Документы»).
  const urlSection = get('section') === 'documents' ? 'branding' : get('section');
  const activeSection: SettingsSectionKey = sections.some((section) => section.key === urlSection)
    ? (urlSection as SettingsSectionKey)
    : defaultSettingsSection();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t('settings.title')}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t('settings.subtitle')}</p>
      </div>

      <SettingsLayout
        sections={sections.map((section) => ({
          key: section.key,
          label: t(section.labelKey),
          group: section.group,
        }))}
        activeSection={activeSection}
        onSelectSection={(key) => set({ section: key })}
      >
        <SectionContent sectionKey={activeSection} />
      </SettingsLayout>
    </div>
  );
}

/** Маппинг секция → существующий компонент (монтируется как есть, spec PR 1). */
function SectionContent({ sectionKey }: { sectionKey: SettingsSectionKey }): ReactNode {
  switch (sectionKey) {
    case 'profile':
      return <ProfileSection />;
    case 'security':
      return <SecuritySection />;
    case 'company':
      // ТОЛЬКО юр.реквизиты компании (бренд переехал в `branding`).
      return <CompanyTab />;
    case 'branding':
      // «Бланк и бренд» — PDF-letterhead/тема/бланк КП (группа «Документы»), только продавец.
      return <CompanyBrandingSection />;
    case 'defaults':
      return <CompanyDefaultsSettings />;
    case 'numbering':
      return <CompanyNumberingSettings />;
    case 'templates':
      return <ChargeTemplatesSettings />;
    case 'doc-templates':
      return <DocumentTemplatesSettings />;
    case 'team':
      return <CompanyTeamSettings />;
    case 'platform':
      return <PlatformSettings />;
  }
}

/**
 * «Бланк и бренд» (группа «Документы», решение владельца 27-07) — PDF-letterhead/тема/бланк КП.
 * Выделено из прежней композиции company: юр.реквизиты (CompanyTab) остались в «Компании», а
 * всё «как выглядит документ» переехало сюда. Секция гейтится на продавца (sells) в
 * settingsSections, поэтому showBranding-условие тут больше не нужно.
 */
function CompanyBrandingSection() {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{t('settings.company.brandingSubtitle')}</h2>
        <p className="text-sm text-muted-foreground mt-1">{t('settings.company.brandingSubtitleHint')}</p>
      </div>
      <CompanyDocumentProfileSettings />
    </div>
  );
}
