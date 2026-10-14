import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import { catalogApi, type Product, type PublishedCatalogItem } from '@/api/catalogApi';
import type { ProductFormState } from '@/components/Shared/product-form/useProductForm';
import { ClientLayerSection } from '../ClientLayerSection';
import { InternalLayerSection } from '../InternalLayerSection';
import { SECTION_BY_REQUIREMENT, SECTION_IDS } from '../anchors';

/**
 * M1-ERP-07 — карточка в два слоя: «Для клиента» (опубликованный) и «Только для сотрудников»
 * (внутренний). Видимость меняет только право `catalog.publish`; политика исполнения — только у
 * услуги; «Глазами клиента» печатает ровно `client_preview` сервера.
 */

const userStoreRef = vi.hoisted(() => ({ permissions: [] as string[] }));

vi.mock('@/store/userStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/store/userStore')>();
  return {
    ...actual,
    useUserStore: (selector: (s: { capabilities: { permissions: string[] } }) => unknown) =>
      selector({ capabilities: { permissions: userStoreRef.permissions } }),
  };
});

vi.mock('@/components/Shared/product-form/OfferSection', () => ({
  OfferSection: () => <div data-testid="offer-section" />,
}));

vi.mock('@/api/catalogApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/catalogApi')>();
  return { ...actual, catalogApi: { ...actual.catalogApi, setProductVisibility: vi.fn() } };
});

const preview: PublishedCatalogItem = {
  id: 7,
  kind: 'service',
  name: 'Монтаж щита',
  description: 'Монтаж на объекте',
  unit: 'час',
  category: 'Монтаж',
  fulfillment_policy: 'time',
  price: null,
  availability: null,
  lead_time_days: null,
  images: [],
  documents: [],
  attributes: [],
};

function makeProduct(overrides: Partial<Product> = {}): Product {
  return {
    id: 7,
    name: 'Монтаж щита',
    description: '',
    sku: 'УС-1',
    status: 1,
    status_name: 'Черновик',
    status_code: 'DRAFT',
    domain_type: 2,
    domain_type_name: 'Услуги',
    visibility: 'on_request',
    client_preview: preview,
    ...overrides,
  };
}

function makeForm(overrides: Partial<ProductFormState> = {}): ProductFormState {
  return {
    draft: { name: 'Монтаж щита', fulfillment_policy: 'time' },
    update: vi.fn(),
    currencies: [{ id: 1, code: 'UZS', name: 'Сум' }],
    kind: 'service',
    sellerMode: true,
    ...overrides,
  } as unknown as ProductFormState;
}

beforeEach(() => {
  userStoreRef.permissions = [];
  vi.mocked(catalogApi.setProductVisibility).mockReset();
});

describe('ClientLayerSection', () => {
  it('shows the fulfillment policy only for a service', () => {
    const { unmount } = renderWithProviders(<ClientLayerSection form={makeForm()} product={makeProduct()} />);
    expect(screen.getByText('Политика исполнения')).toBeInTheDocument();
    unmount();

    renderWithProviders(<ClientLayerSection form={makeForm({ kind: 'goods' })} product={makeProduct()} />);
    expect(screen.queryByText('Политика исполнения')).not.toBeInTheDocument();
  });

  it('without catalog.publish the visibility is read-only', () => {
    userStoreRef.permissions = ['catalog.manage'];
    renderWithProviders(<ClientLayerSection form={makeForm()} product={makeProduct()} />);

    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument();
    expect(screen.getByText('Изменить может роль с правом публикации карточек.')).toBeInTheDocument();
  });

  it('with catalog.publish switches visibility through the action', async () => {
    userStoreRef.permissions = ['catalog.publish'];
    vi.mocked(catalogApi.setProductVisibility).mockResolvedValue(makeProduct({ visibility: 'cabinet' }));
    renderWithProviders(<ClientLayerSection form={makeForm()} product={makeProduct()} />);

    await userEvent.click(screen.getByLabelText(/Цена и наличие в кабинете/));

    await waitFor(() => expect(catalogApi.setProductVisibility).toHaveBeenCalledWith(7, 'cabinet'));
  });

  it('previews the card through the client eyes: price on request, not published', () => {
    renderWithProviders(<ClientLayerSection form={makeForm()} product={makeProduct()} />);

    expect(screen.getByText('Глазами клиента', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Цена по запросу', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('Не опубликована — клиент не видит')).toBeInTheDocument();
  });
});

describe('InternalLayerSection', () => {
  it('shows supplier offers only to a role that sees cost and manages suppliers', () => {
    userStoreRef.permissions = ['catalog.manage', 'supply.manage'];
    const { unmount } = renderWithProviders(<InternalLayerSection form={makeForm()} />);
    expect(screen.getByTestId('offer-section')).toBeInTheDocument();
    expect(screen.getByText('Клиент не видит')).toBeInTheDocument();
    unmount();

    userStoreRef.permissions = [];
    renderWithProviders(<InternalLayerSection form={makeForm()} />);
    expect(screen.queryByTestId('offer-section')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Внутренние заметки')).toBeInTheDocument();
  });
});

describe('completeness anchors', () => {
  it('every publication-threshold code leads to a section', () => {
    for (const code of ['name', 'kind', 'uom', 'category', 'content', 'hs_code', 'fulfillment_policy', 'time_unit', 'list_price']) {
      expect(SECTION_BY_REQUIREMENT[code], code).toBeDefined();
    }
    expect(SECTION_BY_REQUIREMENT.list_price).toBe(SECTION_IDS.client);
  });
});
