/**
 * Settings Hub — единый source of truth секций (spec: Docs/dev/specs/settings-profile-redesign.md §2.2).
 *
 * По аналогии с buildNavigation (ADR-0005, config/navigation.tsx): ОДНА функция строит список
 * секций из деклараций с гейтингом по capabilities/permissions; секции СКРЫВАЮТСЯ, не
 * дизейблятся. Гейтинг воспроизводит прежний SettingsPage/ProfilePage байт-в-байт:
 *   - isAdmin = SystemRole ADMIN (Platform Operator, ADR-0002);
 *   - canEditCompany = OWNER || settings.edit || charge_templates.manage (ADR-0005 U2);
 *   - seller-секции (documents/defaults/numbering/templates) за can_sell И companySells:
 *     /me.capabilities.can_sell — флаг УЧАСТНИКА (CompanyMember.can_sell) и не знает тип
 *     компании, поэтому один он показывал seller-секции OWNER'у CLIENT-only компании
 *     (нарушение матрицы §5.2). companySells — компания типизирована как продавец
 *     (SUPPLIER/MANUFACTURER в statusEntries); мягче nav'а (без требования verified),
 *     чтобы свежий продавец мог настроить документы до одобрения KYC.
 * UX-гейтинг only — backend enforcement (member_has_permission / KYC / entitlements) независим.
 */
import type { Capabilities } from '@/store/userStore';

export type SettingsSectionKey =
  | 'profile'
  | 'security'
  | 'company'
  | 'documents'
  | 'defaults'
  | 'numbering'
  | 'templates'
  | 'team'
  | 'platform';

export interface SettingsSectionDef {
  key: SettingsSectionKey;
  labelKey: string;
}

/** Inputs the gate needs — mirrors what SettingsPage already reads from the stores. */
export interface SettingsGateInput {
  /** SystemRole ADMIN — platform operator rendered in PlatformAdminShell. */
  isAdmin: boolean;
  /** WorkspaceRole OWNER of the company (authStore user.workspace_role). */
  isOwner: boolean;
  /** Consolidated /me capabilities (userStore) — permissions + can_sell drive the gates. */
  capabilities: Capabilities;
  /** Company is seller-typed (any non-BUYER statusEntry) — see module docstring. */
  companySells: boolean;
}

/**
 * ADR-0005 U2 — company-admin gate on the CompanyRole PERMISSION, not WorkspaceRole alone.
 * Fallback to isOwner when permission data is absent (old /me payload); backend still enforces.
 */
export function canEditCompanySettings(input: SettingsGateInput): boolean {
  const perms = input.capabilities.permissions;
  return input.isOwner || perms.includes('settings.edit') || perms.includes('charge_templates.manage');
}

interface SectionRule {
  def: SettingsSectionDef;
  visible: (input: SettingsGateInput) => boolean;
}

/**
 * Полный каталог секций в порядке отображения (§2.2): profile всегда первый.
 * labelKey переиспользует существующие ключи табов — контент секций тот же.
 */
const SECTION_RULES: SectionRule[] = [
  { def: { key: 'profile', labelKey: 'profile.tabs.personal' }, visible: () => true },
  { def: { key: 'security', labelKey: 'profile.tabs.security' }, visible: () => true },
  // Company: canEditCompany редактирует (CompanyTab); ADMIN видит read-only превью.
  {
    def: { key: 'company', labelKey: 'settings.tabs.company' },
    visible: (input) => input.isAdmin || canEditCompanySettings(input),
  },
  // Seller-секции — прежние подтабы CompanyAdminHub, гейтинг без изменений.
  {
    def: { key: 'documents', labelKey: 'settings.tabs.documentProfile' },
    visible: (input) =>
      !input.isAdmin && canEditCompanySettings(input) && input.capabilities.can_sell && input.companySells,
  },
  {
    def: { key: 'defaults', labelKey: 'settings.tabs.defaults' },
    visible: (input) =>
      !input.isAdmin && canEditCompanySettings(input) && input.capabilities.can_sell && input.companySells,
  },
  {
    def: { key: 'numbering', labelKey: 'settings.tabs.numbering' },
    visible: (input) =>
      !input.isAdmin && canEditCompanySettings(input) && input.capabilities.can_sell && input.companySells,
  },
  {
    def: { key: 'templates', labelKey: 'settings.tabs.templates' },
    visible: (input) =>
      !input.isAdmin && canEditCompanySettings(input) && input.capabilities.can_sell && input.companySells,
  },
  // Team — все не-ADMIN (инвайт-форма гейтится внутри CompanyTeamSettings).
  { def: { key: 'team', labelKey: 'settings.tabs.team' }, visible: (input) => !input.isAdmin },
  // Platform — SystemSettings CRUD, только Platform Operator.
  { def: { key: 'platform', labelKey: 'settings.tabs.platform' }, visible: (input) => input.isAdmin },
];

/** Видимые секции для пользователя — скрытие, не дизейбл (ADR-0005). */
export function buildSettingsSections(input: SettingsGateInput): SettingsSectionDef[] {
  return SECTION_RULES.filter((rule) => rule.visible(input)).map((rule) => rule.def);
}

/**
 * Дефолтная секция — та же логика, что прежние defaultTab у SettingsPage
 * (ADMIN → platform; canEditCompany → company; иначе team); profile при этом
 * всегда первый в СПИСКЕ, но не дефолт.
 */
export function defaultSettingsSection(input: SettingsGateInput): SettingsSectionKey {
  if (input.isAdmin) return 'platform';
  if (canEditCompanySettings(input)) return 'company';
  return 'team';
}
