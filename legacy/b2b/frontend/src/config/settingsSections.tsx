/**
 * Settings Hub — единый source of truth секций (spec: Docs/dev/specs/spec-settings-reorg-2026-07-23.md).
 *
 * По аналогии с buildNavigation (ADR-0005, config/navigation.tsx): ОДНА функция строит список
 * секций из деклараций с гейтингом по capabilities/permissions; секции СКРЫВАЮТСЯ, не
 * дизейблятся.
 *
 * S1 — ПОКАЗ-ГЕЙТ = ПРАВДА СОХРАНЕНИЯ (фикс тупиков): раньше все company-секции показывались по
 * ШИРОКОМУ canEditCompanySettings (isOwner || settings.edit || charge_templates.manage), но
 * сохраняли по УЗКОМУ праву → делегат с одним charge_templates.manage видел 6 секций, работал в 1,
 * остальные 5 — мёртвые заглушки. Теперь каждой секции гейт = точное право, которое её РЕАЛЬНО
 * сохраняет (hasSettingsEdit для company/documents/defaults/numbering/doc-templates; hasChargeManage
 * только для templates=статей расхода; hasTeamManage внутри секции team). Это устранение трения,
 * НЕ новая блокировка (PRODUCT RULE 2) — перестаём ПОКАЗЫВАТЬ несохраняемое.
 *
 * seller-секции (documents/defaults/numbering/templates) дополнительно за can_sell И companySells:
 * /me.capabilities.can_sell — флаг УЧАСТНИКА (CompanyMember.can_sell) и не знает тип компании,
 * поэтому один он показывал seller-секции OWNER'у CLIENT-only компании (нарушение матрицы).
 * companySells — компания типизирована как продавец (SUPPLIER/MANUFACTURER в statusEntries);
 * мягче nav'а (без требования verified), чтобы свежий продавец мог настроить документы до KYC.
 *
 * UX-гейтинг only — backend enforcement (member_has_permission / KYC / entitlements) независим.
 */
import type { Capabilities } from '@/store/userStore';

export type SettingsSectionKey =
  | 'profile'
  | 'security'
  | 'company'
  | 'defaults'
  | 'numbering'
  | 'templates'
  | 'doc-templates'
  | 'team'
  | 'billing'
  | 'platform';

/** Группа сайдбара (S2/S5) — порядок: account → company → sales → team → billing → platform. */
export type SettingsGroupKey = 'account' | 'company' | 'sales' | 'team' | 'billing' | 'platform';

export interface SettingsSectionDef {
  key: SettingsSectionKey;
  labelKey: string;
  group: SettingsGroupKey;
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
 * S1 гейт-хелперы — каждый = точное право, которое РЕАЛЬНО сохраняет секцию.
 * Fallback на isOwner (OWNER всегда имеет все company-права; на случай старого /me payload).
 */
/** settings.edit — редактирует профиль компании, документы, дефолты, нумерацию, шаблоны писем. */
export function hasSettingsEdit(input: SettingsGateInput): boolean {
  return input.isOwner || input.capabilities.permissions.includes('settings.edit');
}
/** charge_templates.manage — редактирует ТОЛЬКО статьи расхода КП (секция templates). */
export function hasChargeManage(input: SettingsGateInput): boolean {
  return input.isOwner || input.capabilities.permissions.includes('charge_templates.manage');
}
/** team.manage — управляет составом команды и ролями (действия внутри секции team). */
export function hasTeamManage(input: SettingsGateInput): boolean {
  return input.isOwner || input.capabilities.permissions.includes('team.manage');
}

/**
 * @deprecated S1 — широкий company-гейт заменён точечными hasSettingsEdit/hasChargeManage/hasTeamManage.
 * Сохранён как OR всех company-прав для мест, которым нужен «любой company-admin» флаг.
 */
export function canEditCompanySettings(input: SettingsGateInput): boolean {
  return hasSettingsEdit(input) || hasChargeManage(input) || hasTeamManage(input);
}

interface SectionRule {
  def: SettingsSectionDef;
  visible: (input: SettingsGateInput) => boolean;
}

const sells = (input: SettingsGateInput) => input.capabilities.can_sell && input.companySells;

/**
 * Полный каталог секций в порядке отображения; порядок групп account→company→sales→team→platform.
 * labelKey переиспользует существующие ключи табов — контент секций тот же.
 */
const SECTION_RULES: SectionRule[] = [
  // ── account ──
  { def: { key: 'profile', labelKey: 'profile.tabs.personal', group: 'account' }, visible: () => true },
  { def: { key: 'security', labelKey: 'profile.tabs.security', group: 'account' }, visible: () => true },
  // ── company ── S4: «Документы и бренд» слита в «Реквизиты и бренд» (P4-дубль реквизитов).
  // Company: hasSettingsEdit редактирует (CompanyTab + PDF-бренд-подраздел для продавца);
  // ADMIN видит read-only превью. Отдельной секции documents больше НЕТ (композиция в SettingsPage).
  {
    def: { key: 'company', labelKey: 'settings.tabs.companyBranding', group: 'company' },
    visible: (input) => input.isAdmin || hasSettingsEdit(input),
  },
  {
    def: { key: 'numbering', labelKey: 'settings.tabs.numbering', group: 'company' },
    visible: (input) => !input.isAdmin && hasSettingsEdit(input) && sells(input),
  },
  // ── sales ──
  {
    def: { key: 'defaults', labelKey: 'settings.tabs.defaults', group: 'sales' },
    visible: (input) => !input.isAdmin && hasSettingsEdit(input) && sells(input),
  },
  // templates = «Статьи расхода КП» — ЕДИНСТВЕННАЯ секция на charge-праве.
  {
    def: { key: 'templates', labelKey: 'settings.tabs.templates', group: 'sales' },
    visible: (input) => !input.isAdmin && hasChargeManage(input) && sells(input),
  },
  // Шаблоны писем и актов — нужны И покупателю, И продавцу (решение владельца), гейт на settings.edit.
  {
    def: { key: 'doc-templates', labelKey: 'settings.tabs.docTemplates', group: 'sales' },
    visible: (input) => !input.isAdmin && hasSettingsEdit(input),
  },
  // ── team ── (виден всем не-ADMIN; действия управления внутри гейтятся hasTeamManage).
  { def: { key: 'team', labelKey: 'settings.tabs.team', group: 'team' }, visible: (input) => !input.isAdmin },
  // ── billing ── (S5/P7) «План и подписка» — витрина плана КОМПАНИИ (read-only), перенос
  // top-level «Подписки» в Настройки. Гейт = компания-продавец (companySells): подписка —
  // продавцовая сущность (T2), покупателю не нужна; ADMIN сюда не ходит (у него свой план в
  // PlatformAdminShell). Права участника не требуются — витрина плана видна всей команде продавца.
  {
    def: { key: 'billing', labelKey: 'settings.tabs.billing', group: 'billing' },
    visible: (input) => !input.isAdmin && input.companySells,
  },
  // ── platform ── SystemSettings CRUD, только Platform Operator.
  { def: { key: 'platform', labelKey: 'settings.tabs.platform', group: 'platform' }, visible: (input) => input.isAdmin },
];

/** Видимые секции для пользователя — скрытие, не дизейбл (ADR-0005). */
export function buildSettingsSections(input: SettingsGateInput): SettingsSectionDef[] {
  return SECTION_RULES.filter((rule) => rule.visible(input)).map((rule) => rule.def);
}

/**
 * Дефолтная секция (S1 — убираем тупик P3: раньше бросало в read-only company/team).
 * ADMIN → platform; все не-админы → profile (всегда видима, никогда не мёртвая).
 */
export function defaultSettingsSection(input: SettingsGateInput): SettingsSectionKey {
  if (input.isAdmin) return 'platform';
  return 'profile';
}
