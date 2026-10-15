import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';

import type { Product, PublishedCatalogItem } from '@/api/catalogApi';
import type { ProductFormState } from '@/components/Shared/product-form/useProductForm';
import { renderWithProviders } from '@/test/renderWithProviders';

import { PublicationSection } from './PublicationSection';

// Секции нужна только часть состояния формы — данные приходят пропсами, API не мокаем.
function makeForm(draft: Partial<Product>, domainCode = 'GENERAL_GOODS'): ProductFormState {
  return {
    draft: { domain_type: 1, ...draft },
    update: vi.fn(),
    currencies: [{ id: 5, code: 'USD', name: 'Доллар' }],
    domainTypes: [{ id: 1, code: domainCode, name: domainCode }],
  } as unknown as ProductFormState;
}

const PREVIEW: PublishedCatalogItem = {
  id: 1,
  kind: 'goods',
  name: 'Подшипник 6205',
  description: '',
  unit: 'шт',
  category: 'Подшипники',
  price: null,
  availability: 'in_stock',
  lead_time_days: 3,
  images: [],
  attributes: [{ name: 'Диаметр', value: '52 мм' }],
};

describe('PublicationSection — опубликованный слой карточки (M1-ERP-07)', () => {
  it('без своей политики показывает политику каталога и «Цена по запросу» в превью', () => {
    const product = { price_visibility_default: 'on_request', client_preview: PREVIEW } as Product;
    renderWithProviders(<PublicationSection form={makeForm({ price_visibility: '' })} product={product} />);

    expect(screen.getByText('По умолчанию: по запросу')).toBeInTheDocument();
    expect(screen.getByLabelText('Так видит клиент')).toHaveTextContent('Цена по запросу');
    expect(screen.getByText('В наличии')).toBeInTheDocument();
    expect(screen.getByText('срок 3 дня')).toBeInTheDocument();
  });

  it('цена в кабинете: цена-витрина обязательна, превью печатает цену с валютой', () => {
    const product = {
      price_visibility_default: 'on_request',
      client_preview: { ...PREVIEW, price: { amount: '1234.50', currency: 'USD' } },
    } as Product;
    renderWithProviders(
      <PublicationSection form={makeForm({ price_visibility: 'cabinet', list_price: '1234.50' })} product={product} />,
    );

    expect(screen.getByText(/Клиент увидит цену-витрину в кабинете/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Цена-витрина/)).toHaveValue(1234.5);
    expect(screen.getByLabelText('Так видит клиент')).toHaveTextContent(/1[\s\u00a0\u202f]?234,50/);
  });

  it('политика исполнения — только у услуги', () => {
    const { unmount } = renderWithProviders(<PublicationSection form={makeForm({})} />);
    expect(screen.queryByText('Как оказывается услуга')).not.toBeInTheDocument();
    unmount();

    renderWithProviders(<PublicationSection form={makeForm({ fulfillment_policy: 'milestones' }, 'SERVICES')} />);
    expect(screen.getByText('Как оказывается услуга')).toBeInTheDocument();
    expect(screen.getByText('По этапам')).toBeInTheDocument();
  });

  it('несохранённая карточка: вместо превью — подсказка сохранить', () => {
    renderWithProviders(<PublicationSection form={makeForm({})} />);
    expect(screen.getByText('Сохраните карточку — здесь появится превью для клиента.')).toBeInTheDocument();
  });
});
