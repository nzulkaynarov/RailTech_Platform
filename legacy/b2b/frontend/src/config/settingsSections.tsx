/**
 * Settings Hub — единый source of truth секций (spec: Docs/old/specs/spec-settings-reorg-2026-07-23.md).
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
 * seller-секции (documents/defaults/numbering/templates) — за `capabilities.can_sell`. Это поле
 * теперь считает сервер тем же предикатом, что и авторизация (`is_seller`: членство с can_sell И
 * компания типа SUPPLIER/MANUFACTURER), поэтому местная поправка на тип компании больше не нужна.
 * Раньше плоский флаг участника показывал seller-секции OWNER'у CLIENT-only компании.
 * Требования verified нет — свежий продавец настраивает документы до KYC.
 *
 * UX-гейтинг only — backend enforcement (member_has_permission / KYC / entitlements) независим.
 */
import type { Capabilities } from '@/store/userStore';

export type SettingsSectionKey =
  | 'profile'
  | 'security'
  | 'company'
  | 'branding'
  | 'defaults'
  | 'numbering'
  | 'templates'
  | 'doc-templates'
  | 'team'
  | 'billing'
  | 'platform';

/** Группа сайдбара — порядок: account → company → documents → sales → team → billing → platform.
 * Группа «documents» (решение владельца 27-07): всё «как выглядят мои документы» — бланк/бренд,
 * шаблоны писем и актов, нумерация — живёт в ОДНОМ месте. Юр.реквизиты компании остаются в
 * «company» (это идентичность, не внешний вид — трёхуровневый принцип настроек). */
export type SettingsGroupKey =
  | 'account'
  | 'company'
  | 'documents'
  | 'sales'
  | 'team'
  | 'billing'
  | 'platform';

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

const sells = (input: SettingsGateInput) => input.capabilities.can_sell;

/**
 * Полный каталог секций в порядке отображения; порядок групп account→company→sales→team→platform.
 * labelKey переиспользует существующие ключи табов — контент секций тот же.
 */
const SECTION_RULES: SectionRule[] = [
  // ── account ──
  { def: { key: 'profile', labelKey: 'profile.tabs.personal', group: 'account' }, visible: () => true },
  { def: { key: 'security', labelKey: 'profile.tabs.security', group: 'account' }, visible: () => true },
  // ── company ── ТОЛЬКО юр.реквизиты компании (CompanyTab): название/ИНН/банк/KYC — идентичность,
  // не внешний вид. PDF-бланк/бренд переехал в группу «documents» (решение владельца 27-07).
  // ADMIN видит read-only превью компании.
  {
    def: { key: 'company', labelKey: 'settings.tabs.company', group: 'company' },
    visible: (input) => input.isAdmin || hasSettingsEdit(input),
  },
  // ── documents ── всё «как выглядят мои документы» в одном месте (владелец 27-07).
  // Бланк и бренд — PDF-letterhead/тема/бланк КП (был подразделом company), продавец.
  {
    def: { key: 'branding', labelKey: 'settings.tabs.branding', group: 'documents' },
    visible: (input) => !input.isAdmin && hasSettingsEdit(input) && sells(input),
  },
  // Шаблоны писем и актов — нужны И покупателю, И продавцу (решение владельца), гейт на settings.edit.
  {
    def: { key: 'doc-templates', labelKey: 'settings.tabs.docTemplates', group: 'documents' },
    visible: (input) => !input.isAdmin && hasSettingsEdit(input),
  },
  // Нумерация документов (была в company) — номер тоже часть документа.
  {
    def: { key: 'numbering', labelKey: 'settings.tabs.numbering', group: 'documents' },
    visible: (input) => !input.isAdmin && hasSettingsEdit(input) && sells(input),
  },
  // ── sales ── бизнес-дефолты КП (маржа/НДС/валюта/срок) + статьи расхода — НЕ внешний вид.
  {
    def: { key: 'defaults', labelKey: 'settings.tabs.defaults', group: 'sales' },
    visible: (input) => !input.isAdmin && hasSettingsEdit(input) && sells(input),
  },
  // templates = «Статьи расхода КП» — ЕДИНСТВЕННАЯ секция на charge-праве.
  {
    def: { key: 'templates', labelKey: 'settings.tabs.templates', group: 'sales' },
    visible: (input) => !input.isAdmin && hasChargeManage(input) && sells(input),
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
