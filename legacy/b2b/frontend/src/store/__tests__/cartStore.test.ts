import { describe, it, expect, beforeEach } from 'vitest';
import { useCartStore } from '../cartStore';
import type { Product } from '@/api/catalogApi';

const mockProduct = (id: number, name = 'Test Product'): Product => ({
  id,
  name,
  sku: `SKU-${id}`,
  description: '',
  domain_type: 1,
  domain_type_name: 'GENERAL_GOODS',
  category: 1,
  manufacturer: 1,
  status: 1,
  status_name: 'PUBLISHED',
  uom: 1,
  gost_drawing: '',
  specifications: {},
  base_price: '100.00',
  equipment_groups: [],
  images: [],
  documents: [],
  offers: [],
  created_at: '',
  updated_at: '',
});

describe('cartStore', () => {
  beforeEach(() => {
    useCartStore.setState({ items: [], isOpen: false });
  });

  it('should initialize with empty cart', () => {
    const state = useCartStore.getState();
    expect(state.items).toHaveLength(0);
    expect(state.isOpen).toBe(false);
  });

  it('should add an item to the cart', () => {
    const { addItem } = useCartStore.getState();
    addItem(mockProduct(1));

    const state = useCartStore.getState();
    expect(state.items).toHaveLength(1);
    expect(state.items[0].product.id).toBe(1);
    expect(state.items[0].quantity).toBe(1);
  });

  it('should increment quantity when adding existing item', () => {
    const { addItem } = useCartStore.getState();
    const product = mockProduct(1);

    addItem(product);
    addItem(product, 3);

    const state = useCartStore.getState();
    expect(state.items).toHaveLength(1);
    expect(state.items[0].quantity).toBe(4);
  });

  it('should remove an item from the cart', () => {
    const { addItem, removeItem } = useCartStore.getState();
    addItem(mockProduct(1));
    addItem(mockProduct(2));

    removeItem(1);

    const state = useCartStore.getState();
    expect(state.items).toHaveLength(1);
    expect(state.items[0].product.id).toBe(2);
  });

  it('should update item quantity', () => {
    const { addItem, updateQuantity } = useCartStore.getState();
    addItem(mockProduct(1));

    updateQuantity(1, 5);

    expect(useCartStore.getState().items[0].quantity).toBe(5);
  });

  it('should remove item when quantity is set to 0', () => {
    const { addItem, updateQuantity } = useCartStore.getState();
    addItem(mockProduct(1));

    updateQuantity(1, 0);

    expect(useCartStore.getState().items).toHaveLength(0);
  });

  it('should clear all items', () => {
    const { addItem, clearCart } = useCartStore.getState();
    addItem(mockProduct(1));
    addItem(mockProduct(2));

    clearCart();

    expect(useCartStore.getState().items).toHaveLength(0);
  });

  it('should toggle cart open/close', () => {
    const { toggleCart } = useCartStore.getState();

    toggleCart();
    expect(useCartStore.getState().isOpen).toBe(true);

    toggleCart();
    expect(useCartStore.getState().isOpen).toBe(false);
  });

  it('should add bulk products without duplicates', () => {
    const { addItem, addBulk } = useCartStore.getState();
    addItem(mockProduct(1));

    addBulk([mockProduct(1), mockProduct(2), mockProduct(3)]);

    const state = useCartStore.getState();
    expect(state.items).toHaveLength(3);
    // First item keeps original quantity (not overwritten)
    expect(state.items[0].quantity).toBe(1);
  });

  it('should open and close cart explicitly', () => {
    const { openCart, closeCart } = useCartStore.getState();

    openCart();
    expect(useCartStore.getState().isOpen).toBe(true);

    closeCart();
    expect(useCartStore.getState().isOpen).toBe(false);
  });
});
