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
    kyc_level: 'L2_VERIFIED',
    can_buy: true,
    can_sell: false,
    subscription_active: false,
    can_send_quotes: false,
    quote_send_is_demo: false,
    permissions: [],
    is_platform_admin: false,
    operator_permissions: null,
    ...overrides,
  };
}

function makeGate(overrides: Partial<SettingsGateInput> = {}): SettingsGateInput {
  return {
    isAdmin: false,
    isOwner: false,
    capabilities: makeCapabilities(),
    companySells: true,
    ...overrides,
  };
}

function sectionKeys(input: SettingsGateInput): string[] {
  return buildSettingsSections(input).map((section) => section.key);
}

describe('buildSettingsSections — S1 гейтинг = правда сохранения (spec-settings-reorg-2026-07-23)', () => {
  it('Platform ADMIN: profile/security/company-preview/platform; дефолт=platform', () => {
    const gate = makeGate({
      isAdmin: true,
      capabilities: makeCapabilities({ is_platform_admin: true, can_sell: true }),
    });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'company', 'platform']);
    expect(defaultSettingsSection(gate)).toBe('platform');
  });

  it('OWNER компании-продавца (can_sell): все 9 tenant-секций, без platform; дефолт=profile', () => {
    const gate = makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: true }) });
    expect(sectionKeys(gate)).toEqual([
      'profile', 'security', 'company', 'documents', 'numbering', 'defaults', 'templates',
      'doc-templates', 'team',
    ]);
    expect(defaultSettingsSection(gate)).toBe('profile');
  });

  it('OWNER компании-покупателя: без seller-секций, doc-templates виден (письма нужны обоим)', () => {
    const gate = makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: false }) });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'company', 'doc-templates', 'team']);
    expect(defaultSettingsSection(gate)).toBe('profile');
  });

  it('OWNER CLIENT-only компании с can_sell=true у участника: seller-секции скрыты', () => {
    // /me.capabilities.can_sell — флаг CompanyMember и не знает тип компании; без companySells
    // такой OWNER видел documents/numbering/defaults/templates.
    const gate = makeGate({
      isOwner: true,
      companySells: false,
      capabilities: makeCapabilities({ can_sell: true }),
    });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'company', 'doc-templates', 'team']);
  });

  it('рядовой член команды без прав: только profile/security/team; дефолт=profile', () => {
    const gate = makeGate({ capabilities: makeCapabilities({ can_sell: true }) });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'team']);
    expect(defaultSettingsSection(gate)).toBe('profile');
  });

  it('settings.edit-делегат (без OWNER): company/documents/numbering/defaults/doc-templates — но НЕ templates(charge)', () => {
    const gate = makeGate({
      capabilities: makeCapabilities({ can_sell: true, permissions: ['settings.edit'] }),
    });
    expect(sectionKeys(gate)).toEqual([
      'profile', 'security', 'company', 'documents', 'numbering', 'defaults', 'doc-templates', 'team',
    ]);
    expect(sectionKeys(gate)).not.toContain('templates');
    expect(defaultSettingsSection(gate)).toBe('profile');
  });

  it('charge-делегат (charge_templates.manage): profile/security/templates/team — БЕЗ мёртвых company-секций (фикс тупиков)', () => {
    const gate = makeGate({
      capabilities: makeCapabilities({ can_sell: true, permissions: ['charge_templates.manage'] }),
    });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'templates', 'team']);
    // именно эти company-секции больше НЕ показываются как заглушки:
    for (const dead of ['company', 'documents', 'numbering', 'defaults', 'doc-templates']) {
      expect(sectionKeys(gate)).not.toContain(dead);
    }
    expect(defaultSettingsSection(gate)).toBe('profile');
  });

  it('гейт-хелперы: точное право открывает свою секцию, OWNER открывает все', () => {
    const owner = makeGate({ isOwner: true });
    expect(hasSettingsEdit(owner)).toBe(true);
    expect(hasChargeManage(owner)).toBe(true);
    expect(hasTeamManage(owner)).toBe(true);

    const chargeOnly = makeGate({ capabilities: makeCapabilities({ permissions: ['charge_templates.manage'] }) });
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
      makeGate({ isAdmin: true, capabilities: makeCapabilities({ is_platform_admin: true }) }),
      makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: true }) }),
      makeGate({ isOwner: true }),
      makeGate(),
      makeGate({ capabilities: makeCapabilities({ permissions: ['settings.edit'] }) }),
      makeGate({ capabilities: makeCapabilities({ permissions: ['charge_templates.manage'] }) }),
    ];
    for (const gate of roleMatrix) {
      const keys = sectionKeys(gate);
      expect(keys.length).toBeGreaterThan(0);
      expect(keys[0]).toBe('profile');
      expect(keys).toContain(defaultSettingsSection(gate));
    }
  });
});

describe('buildSettingsSections — S2 группировка', () => {
  it('каждая секция несёт корректный group-ключ', () => {
    const gate = makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: true }) });
    const byKey = new Map(buildSettingsSections(gate).map((section) => [section.key, section.group]));
    expect(byKey.get('profile')).toBe('account');
    expect(byKey.get('security')).toBe('account');
    expect(byKey.get('company')).toBe('company');
    expect(byKey.get('documents')).toBe('company');
    expect(byKey.get('numbering')).toBe('company');
    expect(byKey.get('defaults')).toBe('sales');
    expect(byKey.get('templates')).toBe('sales');
    expect(byKey.get('doc-templates')).toBe('sales');
    expect(byKey.get('team')).toBe('team');
  });

  it('platform-секция в группе platform', () => {
    const gate = makeGate({ isAdmin: true, capabilities: makeCapabilities({ is_platform_admin: true }) });
    const platform = buildSettingsSections(gate).find((section) => section.key === 'platform');
    expect(platform?.group).toBe('platform');
  });

  it('группы идут в порядке account→company→sales→team→platform (первое появление)', () => {
    const gate = makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: true }) });
    const groupOrder: string[] = [];
    for (const section of buildSettingsSections(gate)) {
      if (!groupOrder.includes(section.group)) groupOrder.push(section.group);
    }
    expect(groupOrder).toEqual(['account', 'company', 'sales', 'team']);
  });
});
