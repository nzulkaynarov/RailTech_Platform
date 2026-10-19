import { describe, expect, it } from 'vitest';

import { canSwitchToCrm } from '../crmSwitch';

describe('canSwitchToCrm — переключатель в шапке ERP (FIX-11)', () => {
  it.each([
    [{ sso_enabled: true, crm_access: true }, true],
    [{ sso_enabled: true, crm_access: false }, false], // локальный пользователь без сопоставления
    [{ sso_enabled: false, crm_access: true }, false],
    [{ sso_enabled: false, crm_access: false }, false],
    [{ sso_enabled: true }, false], // старый ответ сервера без поля
    [{ crm_access: true }, false],
    [{}, false],
    [null, false],
    [undefined, false],
  ])('%j → %s', (capabilities, expected) => {
    expect(canSwitchToCrm(capabilities)).toBe(expected);
  });
});
