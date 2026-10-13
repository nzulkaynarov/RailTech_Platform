import { describe, expect, it } from 'vitest';

import { regionName } from '../regionName';

describe('regionName', () => {
  it('переводит код страны на язык интерфейса без рукописных словарей', () => {
    expect(regionName('DE', 'ru')).toBe('Германия');
    expect(regionName('DE', 'en')).toBe('Germany');
    expect(regionName('UZ', 'ru')).toBe('Узбекистан');
  });

  it('понимает региональный тег языка (en-US → en)', () => {
    // Ровно эта ловушка ломала ленты событий: ресурсы лежат под «en», а язык приходит «en-US».
    expect(regionName('FR', 'en-US')).toBe('France');
  });

  it('возвращает имя из справочника, когда код стандарту неизвестен', () => {
    // Оператор может завести свою строку через админку — сырой код показывать нельзя.
    expect(regionName('ZZ', 'ru', 'Особая территория')).toBe('Особая территория');
    expect(regionName('', 'ru', 'Не указана')).toBe('Не указана');
  });

  it('нормализует регистр и пробелы кода', () => {
    expect(regionName(' de ', 'ru')).toBe('Германия');
  });
});
