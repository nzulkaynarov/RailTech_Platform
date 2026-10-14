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
    can_buy: true,
    can_sell: false,
    permissions: [],
    ...overrides,
  };
}

function makeGate(overrides: Partial<SettingsGateInput> = {}): SettingsGateInput {
  return {
    isOwner: false,
    capabilities: makeCapabilities(),
    ...overrides,
  };
}

function sectionKeys(input: SettingsGateInput): string[] {
  return buildSettingsSections(input).map((section) => section.key);
}

describe('buildSettingsSections — S1 гейтинг = правда сохранения (spec-settings-reorg-2026-07-23)', () => {
  it('OWNER компании-продавца (can_sell): все tenant-секции (группа documents: branding/doc-templates/numbering; +platform); дефолт=profile', () => {
    // M1-ERP-02: операторской плоскости нет; platform-секция (НДС/курс/имя/2FA) до ролей
    // бэк-офиса (M1-ERP-05) открыта OWNER'у как «Администратору».
    const gate = makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: true }) });
    expect(sectionKeys(gate)).toEqual([
      'profile', 'security', 'company', 'branding', 'doc-templates', 'numbering',
      'defaults', 'templates', 'team', 'platform',
    ]);
    expect(defaultSettingsSection()).toBe('profile');
  });

  it('OWNER компании-покупателя: без seller-секций, doc-templates виден (письма нужны обоим)', () => {
    const gate = makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: false }) });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'company', 'doc-templates', 'team', 'platform']);
    expect(defaultSettingsSection()).toBe('profile');
  });

  it('OWNER CLIENT-only компании: seller-секции скрыты (can_sell приходит с сервера уже ложным)', () => {
    // `capabilities.can_sell` = серверный `is_seller` (членство И тип компании), поэтому у OWNER'а
    // покупательской компании он ложен независимо от флага участника. Проверка держит инвариант:
    // если сервер вернёт правду, секции появятся — значит гейт читает именно эту правду.
    const gate = makeGate({
      isOwner: true,
      capabilities: makeCapabilities({ can_sell: false }),
    });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'company', 'doc-templates', 'team', 'platform']);
  });

  it('рядовой член команды-продавца без прав: profile/security/team; дефолт=profile', () => {
    const gate = makeGate({ capabilities: makeCapabilities({ can_sell: true }) });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'team']);
    expect(defaultSettingsSection()).toBe('profile');
  });

  it('settings.edit-делегат (без OWNER): company/branding/doc-templates/numbering/defaults — но НЕ templates(charge) и НЕ platform', () => {
    const gate = makeGate({
      capabilities: makeCapabilities({ can_sell: true, permissions: ['settings.edit'] }),
    });
    expect(sectionKeys(gate)).toEqual([
      'profile', 'security', 'company', 'branding', 'doc-templates', 'numbering', 'defaults', 'team',
    ]);
    expect(sectionKeys(gate)).not.toContain('templates');
    expect(sectionKeys(gate)).not.toContain('platform');
    expect(defaultSettingsSection()).toBe('profile');
  });

  it('charge-делегат (charge_templates.manage): profile/security/templates/team — БЕЗ мёртвых company-секций (фикс тупиков)', () => {
    const gate = makeGate({
      capabilities: makeCapabilities({ can_sell: true, permissions: ['charge_templates.manage'] }),
    });
    expect(sectionKeys(gate)).toEqual(['profile', 'security', 'templates', 'team']);
    // именно эти company/documents-секции больше НЕ показываются как заглушки:
    for (const dead of ['company', 'branding', 'numbering', 'defaults', 'doc-templates']) {
      expect(sectionKeys(gate)).not.toContain(dead);
    }
    expect(defaultSettingsSection()).toBe('profile');
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
      expect(keys).toContain(defaultSettingsSection());
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
    // Группа «documents» (владелец 27-07): бланк/бренд + шаблоны писем + нумерация.
    expect(byKey.get('branding')).toBe('documents');
    expect(byKey.get('doc-templates')).toBe('documents');
    expect(byKey.get('numbering')).toBe('documents');
    // sales = бизнес-дефолты КП + статьи расхода (не внешний вид).
    expect(byKey.get('defaults')).toBe('sales');
    expect(byKey.get('templates')).toBe('sales');
    expect(byKey.get('team')).toBe('team');
  });

  it('platform-секция в группе platform', () => {
    const gate = makeGate({ isOwner: true });
    const platform = buildSettingsSections(gate).find((section) => section.key === 'platform');
    expect(platform?.group).toBe('platform');
  });

  it('группы идут в порядке account→company→documents→sales→team→platform (первое появление)', () => {
    const gate = makeGate({ isOwner: true, capabilities: makeCapabilities({ can_sell: true }) });
    const groupOrder: string[] = [];
    for (const section of buildSettingsSections(gate)) {
      if (!groupOrder.includes(section.group)) groupOrder.push(section.group);
    }
    expect(groupOrder).toEqual(['account', 'company', 'documents', 'sales', 'team', 'platform']);
  });
});
