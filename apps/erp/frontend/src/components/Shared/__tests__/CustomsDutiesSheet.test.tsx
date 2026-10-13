import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import { CustomsDutiesSheet } from '../CustomsDutiesSheet';

const countries = [
  { id: 1, code: 'CN', name: 'Китай', alpha2: 'CN', alpha3: 'CHN', iso_numeric: '156', vat_rate: '13.00', sort_order: 40, is_active: true },
];

const duties = {
  hs_code: '8703101100',
  hs_name: 'Автомобили легковые',
  origin: 'CN',
  payments: [
    { code: '20', source_label: 'Bojxona boji', rate: '30.0 %', legal_basis: 'ПП-4470 от 02.10.2019 г.' },
    { code: '29', source_label: 'QQS', rate: '', legal_basis: '' },
    { code: '', source_label: "Utilizatsiya yig'imi", rate: 'по ПКМ №347', legal_basis: 'ПКМ №347' },
  ],
  permits: [
    { organization: 'Агентство', document: 'Сертификат соответствия', legal_basis: 'ПКМ-43', document_kind: 'Сертификат' },
  ],
  fetched_at: '2026-08-04T10:00:00Z',
  source_url: 'https://tarif.customs.uz/calc/view_calc.jsp',
};

const useCustomsDuties = vi.fn();

vi.mock('@/hooks/useMasterData', () => ({
  useCountries: () => ({ data: countries, isLoading: false }),
  useCustomsDuties: (...args: unknown[]) => useCustomsDuties(...args),
}));

describe('CustomsDutiesSheet', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCustomsDuties.mockReturnValue({ data: undefined, isFetching: false, isError: false });
  });

  it('до выбора страны данные не запрашиваются — ставка без происхождения бессмысленна', () => {
    renderWithProviders(<CustomsDutiesSheet hsCode="8703101100" open onOpenChange={vi.fn()} />);

    expect(screen.getByText('Выберите страну происхождения, чтобы увидеть платежи.')).toBeInTheDocument();
    // хук вызван с пустым кодом страны → запрос выключен
    expect(useCustomsDuties).toHaveBeenCalledWith('8703101100', '');
  });

  it('показывает ставки нашими подписями, а не узбекскими из источника', () => {
    useCustomsDuties.mockReturnValue({ data: duties, isFetching: false, isError: false });
    renderWithProviders(<CustomsDutiesSheet hsCode="8703101100" open onOpenChange={vi.fn()} />);

    expect(screen.getByText('Таможенная пошлина')).toBeInTheDocument();
    expect(screen.getByText('30.0 %')).toBeInTheDocument();
    expect(screen.getByText('ПП-4470 от 02.10.2019 г.')).toBeInTheDocument();
    // строка без кода платежа сохраняет подпись источника — это реальные деньги импортёра
    expect(screen.getByText("Utilizatsiya yig'imi")).toBeInTheDocument();
  });

  it('пустая ставка рисуется «—», а НЕ «0%» — за таможню не додумываем', () => {
    useCustomsDuties.mockReturnValue({ data: duties, isFetching: false, isError: false });
    renderWithProviders(<CustomsDutiesSheet hsCode="8703101100" open onOpenChange={vi.fn()} />);

    const vatRow = screen.getByText('НДС').closest('tr');
    expect(vatRow).not.toBeNull();
    expect(vatRow?.textContent).toContain('—');
    expect(vatRow?.textContent).not.toContain('0 %');
  });

  it('показывает разрешительные документы и подпись источника', () => {
    useCustomsDuties.mockReturnValue({ data: duties, isFetching: false, isError: false });
    renderWithProviders(<CustomsDutiesSheet hsCode="8703101100" open onOpenChange={vi.fn()} />);

    expect(screen.getByText('Сертификат соответствия')).toBeInTheDocument();
    expect(screen.getByText(/По данным ГТК РУз/)).toBeInTheDocument();
    expect(screen.getByText(/Не является таможенной консультацией/)).toBeInTheDocument();
  });

  it('источник лёг — вместо тупика ссылка на калькулятор ГТК', async () => {
    const user = userEvent.setup();
    useCustomsDuties.mockReturnValue({ data: undefined, isFetching: false, isError: true });
    renderWithProviders(<CustomsDutiesSheet hsCode="8703101100" open onOpenChange={vi.fn()} />);

    // Деградация показывается ПОСЛЕ выбора страны: до него запроса не было и ошибки быть не может.
    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByText('Китай'));

    expect(screen.getByText('Не удалось получить данные ГТК')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /Открыть калькулятор ГТК/ });
    expect(link).toHaveAttribute('href', 'https://tarif.customs.uz');
  });
});
