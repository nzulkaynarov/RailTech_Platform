import { describe, expect, it } from 'vitest';

import {
  buildSettingsSections,
  canEditCompanySettings,
  defaultSettingsSection,
  hasChargeManage,
  hasSettingsEdit,
  hasTeamManage,
  type SettingsGateInput,
} from '@/config/settingsSections';
import type { Capabilities } from '@/store/userStore';

function makeCapabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    permissions: [],
    ...overrides,
  };
}

// Администратор ERP (is_superuser): в /me весь каталог прав (M1-ERP-05).
const ALL_PERMISSIONS = ['settings.edit', 'settings.charge_templates', 'team.manage', 'quote.build'];
const ADMIN: Partial<SettingsGateInput> = { isSuperuser: true, capabilities: { permissions: ALL_PERMISSIONS } };
const HEAD: Partial<SettingsGateInput> = { capabilities: { permissions: ALL_PERMISSIONS } };

function makeGate(overrides: Partial<SettingsGateInput> = {}): SettingsGateInput {
  return {
    isSuperuser: false,
    capabilities: makeCapabilities(),
    ...overrides,
  };
}

function sectionKeys(input: SettingsGateInput): string[] {
  return buildSettingsSections(input).map((section) => section.key);
}

describe('buildSettingsSections — S1 гейтинг = правда сохранения (spec-settings-reorg-2026-07-23)', () => {
  it('администратор (is_superuser): все секции (группа documents: branding/doc-templates/email-templates/numbering; +platform); дефолт=profile', () => {
    // M1-ERP-05: platform-секция (НДС/курс/имя/2FA) — только администратор.
    const gate = makeGate(ADMIN);
    expect(sectionKeys(gate)).toEqual([
      'profile', 'security', 'company', 'master-data', 'categories', 'branding', 'doc-templates', 'email-templates', 'numbering',
      'defaults', 'templates', 'team', 'platform', 'crm-integration',
    ]);
    expect(defaultSettingsSection()).toBe('profile');
  });

  it('«Руководитель» (все права, не администратор): всё, кроме platform', () => {
    const gate = makeGate(HEAD);
    expect(sectionKeys(gate)).toEqual([
      'profile', 'security', 'company', 'master-data', 'categories', 'branding', 'doc-templates', 'email-templates', 'numbering',
      'defaults', 'templates', 'team',
    ]);
  });

  it('должность OWNER больше ничего не открывает: без прав — только profile/security/team', () => {
    expect(sectionKeys(makeGate())).toEqual(['profile', 'security', 'team']);
  });

  it('сторон нет (M1-ERP-02 волна 3): у администратора бланк, нумерация, дефолты и статьи расхода видны всегда', () => {
    const gate = makeGate(ADMIN);
    for (const key of ['branding', 'numbering', 'defaults', 'templates']) {
      expect(sectionKeys(gate)).toContain(key);
    }
  });

  it('рядовой член команды без прав: profile/security/team; дефолт=profile', () => {
    const gate = makeGate({ capabilities: makeCapabilities() });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'team']);
    expect(defaultSettingsSection()).toBe('profile');
  });

  it('settings.edit-делегат: company/master-data/categories/branding/doc-templates/email-templates/numbering/defaults — но НЕ templates(charge) и НЕ platform', () => {
    const gate = makeGate({
      capabilities: makeCapabilities({ permissions: ['settings.edit'] }),
    });
    expect(sectionKeys(gate)).toEqual([
      'profile', 'security', 'company', 'master-data', 'categories', 'branding', 'doc-templates', 'email-templates', 'numbering', 'defaults', 'team',
    ]);
    expect(sectionKeys(gate)).not.toContain('templates');
    expect(sectionKeys(gate)).not.toContain('platform');
    expect(sectionKeys(gate)).not.toContain('crm-integration');
    expect(defaultSettingsSection()).toBe('profile');
  });

  it('catalog.manage открывает categories в company, но не другие закрытые секции', () => {
    const gate = makeGate({
      capabilities: makeCapabilities({ permissions: ['catalog.manage'] }),
    });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'categories', 'team']);
  });

  it('несуществующий код catalog.edit (FIX-42) ничего не открывает', () => {
    const gate = makeGate({
      capabilities: makeCapabilities({ permissions: ['catalog.edit'] }),
    });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'team']);
  });

  it('charge-делегат (charge_templates.manage): profile/security/templates/team — БЕЗ мёртвых company-секций (фикс тупиков)', () => {
    const gate = makeGate({
      capabilities: makeCapabilities({ permissions: ['settings.charge_templates'] }),
    });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'templates', 'team']);
    // именно эти company/documents-секции больше НЕ показываются как заглушки:
    for (const dead of ['company', 'master-data', 'categories', 'branding', 'numbering', 'defaults', 'doc-templates', 'email-templates']) {
      expect(sectionKeys(gate)).not.toContain(dead);
    }
    expect(defaultSettingsSection()).toBe('profile');
  });

  it('гейт-хелперы: точное право открывает свою секцию, администратор — все', () => {
    const owner = makeGate(ADMIN);
    expect(hasSettingsEdit(owner)).toBe(true);
    expect(hasChargeManage(owner)).toBe(true);
    expect(hasTeamManage(owner)).toBe(true);

    const chargeOnly = makeGate({ capabilities: makeCapabilities({ permissions: ['settings.charge_templates'] }) });
    expect(hasChargeManage(chargeOnly)).toBe(true);
    expect(hasSettingsEdit(chargeOnly)).toBe(false);
    expect(hasTeamManage(chargeOnly)).toBe(false);

    const teamOnly = makeGate({ capabilities: makeCapabilities({ permissions: ['team.manage'] }) });
    expect(hasTeamManage(teamOnly)).toBe(true);
    expect(hasSettingsEdit(teamOnly)).toBe(false);
    // legacy OR-хелпер видит любое company-право
    expect(canEditCompanySettings(teamOnly)).toBe(true);
  });

  it('ни у одной роли список не пуст, profile всегда первый, дефолт всегда видим', () => {
    const roleMatrix: SettingsGateInput[] = [
      makeGate(ADMIN),
      makeGate(ADMIN),
      makeGate(),
      makeGate({ capabilities: makeCapabilities({ permissions: ['settings.edit'] }) }),
      makeGate({ capabilities: makeCapabilities({ permissions: ['settings.charge_templates'] }) }),
    ];
    for (const gate of roleMatrix) {
      const keys = sectionKeys(gate);
      expect(keys.length).toBeGreaterThan(0);
      expect(keys[0]).toBe('profile');
      expect(keys).toContain(defaultSettingsSection());
    }
  });
});

describe('buildSettingsSections — S2 группировка', () => {
  it('каждая секция несёт корректный group-ключ', () => {
    const gate = makeGate(ADMIN);
    const byKey = new Map(buildSettingsSections(gate).map((section) => [section.key, section.group]));
    expect(byKey.get('profile')).toBe('account');
    expect(byKey.get('security')).toBe('account');
    expect(byKey.get('company')).toBe('company');
    expect(byKey.get('master-data')).toBe('company');
    expect(byKey.get('categories')).toBe('company');
    // Группа «documents» (владелец 27-07): бланк/бренд + шаблоны писем + нумерация.
    expect(byKey.get('branding')).toBe('documents');
    expect(byKey.get('doc-templates')).toBe('documents');
    expect(byKey.get('email-templates')).toBe('documents');
    expect(byKey.get('numbering')).toBe('documents');
    // sales = бизнес-дефолты КП + статьи расхода (не внешний вид).
    expect(byKey.get('defaults')).toBe('sales');
    expect(byKey.get('templates')).toBe('sales');
    expect(byKey.get('team')).toBe('team');
  });

  it('platform-секция в группе platform', () => {
    const gate = makeGate(ADMIN);
    const platform = buildSettingsSections(gate).find((section) => section.key === 'platform');
    expect(platform?.group).toBe('platform');
  });

  it('группы идут в порядке account→company→documents→sales→team→platform (первое появление)', () => {
    const gate = makeGate(ADMIN);
    const groupOrder: string[] = [];
    for (const section of buildSettingsSections(gate)) {
      if (!groupOrder.includes(section.group)) groupOrder.push(section.group);
    }
    expect(groupOrder).toEqual(['account', 'company', 'documents', 'sales', 'team', 'platform']);
  });
});
