import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import { CountrySelect } from '../CountrySelect';

const countries = [
  { id: 1, code: 'UZ', name: 'Узбекистан', alpha2: 'UZ', alpha3: 'UZB', iso_numeric: '860', vat_rate: '12.00', sort_order: 10, is_active: true },
  { id: 2, code: 'DE', name: 'Германия', alpha2: 'DE', alpha3: 'DEU', iso_numeric: '276', vat_rate: '19.00', sort_order: 50, is_active: true },
  { id: 3, code: 'JP', name: 'Япония', alpha2: 'JP', alpha3: 'JPN', iso_numeric: '392', vat_rate: null, sort_order: 100, is_active: true },
];

vi.mock('@/hooks/useMasterData', () => ({
  useCountries: () => ({ data: countries, isLoading: false }),
}));

describe('CountrySelect', () => {
  beforeEach(() => vi.clearAllMocks());

  it('показывает выбранную страну на языке интерфейса', () => {
    renderWithProviders(<CountrySelect value="2" onChange={vi.fn()} />);
    expect(screen.getByRole('combobox')).toHaveTextContent('Германия');
  });

  it('ищет и по названию, и по коду — менеджер ВЭД помнит код', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CountrySelect value="" onChange={vi.fn()} />);
    await user.click(screen.getByRole('combobox'));

    await user.type(await screen.findByPlaceholderText('Поиск по названию или коду'), 'JP');
    await waitFor(() => expect(screen.getByText('Япония')).toBeInTheDocument());
    expect(screen.queryByText('Германия')).not.toBeInTheDocument();
  });

  it('отдаёт id выбранной страны и закрывает список', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<CountrySelect value="" onChange={onChange} />);
    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByText('Узбекистан'));

    expect(onChange).toHaveBeenCalledWith('1');
  });

  it('частые торговые партнёры стоят выше прочих стран', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CountrySelect value="" onChange={vi.fn()} />);
    await user.click(screen.getByRole('combobox'));

    const options = await screen.findAllByRole('option');
    expect(options.map((option) => option.textContent)).toEqual([
      expect.stringContaining('Узбекистан'),
      expect.stringContaining('Германия'),
      expect.stringContaining('Япония'),
    ]);
  });
});
