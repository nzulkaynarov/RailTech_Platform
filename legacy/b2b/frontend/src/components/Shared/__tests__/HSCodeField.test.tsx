/**
 * Поле кода ТН ВЭД (волна T1) — автокомплит по справочнику с МЯГКОЙ валидацией.
 *
 * До T1 система требовала то, что негде ввести: очередь номенклатуры писала «не хватает: Код
 * ТН ВЭД», а в форме карточки поля не было вовсе. Паттерн — Shopify: HS-поле это автокомплит
 * в месте работы, а не «сходи в справочник».
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { useState } from 'react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { HSCodeField } from '../HSCodeField';
import { leafName } from '@/lib/hsCode';
import { formatHSCode } from '@/lib/hsCode';
import { catalogApi } from '@/api/catalogApi';

vi.mock('@/api/catalogApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/catalogApi')>();
  return {
    ...original,
    catalogApi: {
      ...original.catalogApi,
      suggestHSCodes: vi.fn().mockResolvedValue([]),
      validateHSCode: vi.fn().mockResolvedValue({ known: true, active: true, name: '' }),
    },
  };
});

const suggestMock = vi.mocked(catalogApi.suggestHSCodes);
const validateMock = vi.mocked(catalogApi.validateHSCode);

beforeEach(() => {
  suggestMock.mockClear();
  validateMock.mockClear();
});

describe('формат и имя', () => {
  it('код печатается группами, как в самой номенклатуре', () => {
    expect(formatHSCode('8482100000')).toBe('8482 10 000 0');
    expect(formatHSCode('8482')).toBe('8482');
    expect(formatHSCode('860721')).toBe('8607 21');
  });

  it('пользователю показывается СОБСТВЕННОЕ имя позиции, а не весь путь по дереву', () => {
    expect(leafName('Подшипники шариковые или роликовые:подшипники шариковые:прочие')).toBe('прочие');
    expect(leafName('Рельсы')).toBe('Рельсы');
  });
});

describe('автокомплит', () => {
  it('печать текста открывает кандидатов из справочника; выбор фиксирует код', async () => {
    suggestMock.mockResolvedValue([
      { code: '8482100000', name: 'Подшипники шариковые:прочие', level: 10, score: 0.9 },
    ]);
    const onChange = vi.fn();
    // Поле контролируемое: без стейтфул-обёртки value застывает и запрос не набирается.
    function Harness() {
      const [value, setValue] = useState('');
      return (
        <HSCodeField
          value={value}
          onChange={(next) => {
            setValue(next);
            onChange(next);
          }}
        />
      );
    }
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.type(screen.getByRole('combobox'), 'подшипник');
    await waitFor(() => expect(suggestMock).toHaveBeenCalled());
    const option = await screen.findByText('8482 10 000 0');
    await user.click(option);

    expect(onChange).toHaveBeenLastCalledWith('8482100000');
  });

  it('свободный ввод остаётся возможным — справочник может быть пуст', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<HSCodeField value="" onChange={onChange} />);

    await user.type(screen.getByRole('combobox'), '99');

    expect(onChange).toHaveBeenCalled();
  });
});

describe('мягкая валидация — подсветка, не блок', () => {
  it('неизвестный код получает жёлтую пометку «нет в справочнике»', async () => {
    validateMock.mockResolvedValue({ known: false, active: false, name: '' });
    renderWithProviders(<HSCodeField value="9999999999" onChange={() => {}} />);

    expect(await screen.findByText(/нет в справочнике/i)).toBeInTheDocument();
  });

  it('код, выведенный из редакции, называет проблему словами', async () => {
    validateMock.mockResolvedValue({ known: true, active: false, name: 'Оси в сборе' });
    renderWithProviders(<HSCodeField value="8607191000" onChange={() => {}} />);

    expect(await screen.findByText(/выведен из редакции/i)).toBeInTheDocument();
  });

  it('действующий код тихо подтверждается именем позиции', async () => {
    validateMock.mockResolvedValue({ known: true, active: true, name: 'Подшипники:прочие' });
    renderWithProviders(<HSCodeField value="8482100000" onChange={() => {}} />);

    expect(await screen.findByText('прочие')).toBeInTheDocument();
  });
});
