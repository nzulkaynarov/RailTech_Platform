import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n';
import { setOperatorName } from '@/i18n/operator';

describe('название оператора в текстах (задача «Н3a2»)', () => {
  afterEach(() => setOperatorName('RailTech'));

  it('берётся из настроек компании, не из кода', async () => {
    await i18n.changeLanguage('ru');
    setOperatorName('Acme Trade');
    expect(i18n.t('app.name')).toBe('Кабинет Acme Trade');
    expect(i18n.t('verify.verifiedSub')).not.toContain('Acme');
  });

  it('не задано — без чужого слова: «Кабинет», не «Кабинет Платформа»', async () => {
    await i18n.changeLanguage('ru');
    setOperatorName(null);
    expect(i18n.t('app.name').trim()).toBe('Кабинет');
  });
});
