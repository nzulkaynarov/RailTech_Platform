import { describe, expect, it } from 'vitest';

import {
  buildSettingsSections,
  canEditCompanySettings,
  defaultSettingsSection,
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

describe('buildSettingsSections — матрица гейтинга (spec §2.2 / §5.2)', () => {
  it('Platform ADMIN: profile/security/company-preview/platform; без team и seller-секций', () => {
    const gate = makeGate({
      isAdmin: true,
      capabilities: makeCapabilities({ is_platform_admin: true, can_sell: true }),
    });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'company', 'platform']);
    expect(defaultSettingsSection(gate)).toBe('platform');
  });

  it('OWNER компании-продавца (can_sell): все 9 tenant-секций, без platform', () => {
    const gate = makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: true }) });
    expect(sectionKeys(gate)).toEqual([
      'profile', 'security', 'company', 'documents', 'defaults', 'numbering', 'templates',
      'doc-templates', 'team',
    ]);
    expect(defaultSettingsSection(gate)).toBe('company');
  });

  it('OWNER компании-покупателя: без seller-секций, но doc-templates виден (письма нужны обоим)', () => {
    const gate = makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: false }) });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'company', 'doc-templates', 'team']);
    expect(defaultSettingsSection(gate)).toBe('company');
  });

  it('OWNER CLIENT-only компании с can_sell=true у участника: seller-секции скрыты (§5.2)', () => {
    // /me.capabilities.can_sell — флаг CompanyMember и не знает тип компании; без
    // companySells такой OWNER видел documents/defaults/numbering/templates.
    const gate = makeGate({
      isOwner: true,
      companySells: false,
      capabilities: makeCapabilities({ can_sell: true }),
    });
    // seller-секции скрыты; company + doc-templates остаются (canEditCompanySettings через OWNER).
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'company', 'doc-templates', 'team']);
  });

  it('член команды без прав: только profile/security/team', () => {
    const gate = makeGate({ capabilities: makeCapabilities({ can_sell: true }) });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'team']);
    expect(defaultSettingsSection(gate)).toBe('team');
  });

  it('делегированный админ компании (settings.edit без OWNER) видит company-секции — ADR-0005 U2', () => {
    const gate = makeGate({
      capabilities: makeCapabilities({ can_sell: true, permissions: ['settings.edit'] }),
    });
    expect(sectionKeys(gate)).toContain('company');
    expect(sectionKeys(gate)).toContain('templates');
    expect(defaultSettingsSection(gate)).toBe('company');
  });

  it('charge_templates.manage тоже открывает company-гейт (как прежний SettingsPage)', () => {
    const gate = makeGate({
      capabilities: makeCapabilities({ permissions: ['charge_templates.manage'] }),
    });
    expect(canEditCompanySettings(gate)).toBe(true);
    expect(sectionKeys(gate)).toContain('company');
  });

  it('ни у одной роли список секций не пуст, profile всегда первый, дефолт всегда видим', () => {
    const roleMatrix: SettingsGateInput[] = [
      makeGate({ isAdmin: true, capabilities: makeCapabilities({ is_platform_admin: true }) }),
      makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: true }) }),
      makeGate({ isOwner: true }),
      makeGate(),
      makeGate({ capabilities: makeCapabilities({ permissions: ['settings.edit'] }) }),
    ];
    for (const gate of roleMatrix) {
      const keys = sectionKeys(gate);
      expect(keys.length).toBeGreaterThan(0);
      expect(keys[0]).toBe('profile');
      expect(keys).toContain(defaultSettingsSection(gate));
    }
  });
});
