import { create } from 'zustand';
import type { Product } from '@/api/catalogApi';

export interface CartItem {
  product: Product;
  quantity: number;
}

interface CartState {
  items: CartItem[];
  isOpen: boolean;

  addItem: (product: Product, qty?: number) => void;
  removeItem: (productId: number) => void;
  updateQuantity: (productId: number, quantity: number) => void;
  clearCart: () => void;
  openCart: () => void;
  closeCart: () => void;
  toggleCart: () => void;

  /** Bulk add from selected IDs + products array */
  addBulk: (products: Product[]) => void;
}

export const useCartStore = create<CartState>()((set, get) => ({
  items: [],
  isOpen: false,

  addItem: (product, qty = 1) => {
    set((state) => {
      const existing = state.items.find((i) => i.product.id === product.id);
      if (existing) {
        return {
          items: state.items.map((i) =>
            i.product.id === product.id
              ? { ...i, quantity: i.quantity + qty }
              : i
          ),
        };
      }
      return { items: [...state.items, { product, quantity: qty }] };
    });
  },

  removeItem: (productId) => {
    set((state) => ({
      items: state.items.filter((i) => i.product.id !== productId),
    }));
  },

  updateQuantity: (productId, quantity) => {
    if (quantity <= 0) {
      get().removeItem(productId);
      return;
    }
    set((state) => ({
      items: state.items.map((i) =>
        i.product.id === productId ? { ...i, quantity } : i
      ),
    }));
  },

  addBulk: (products) => {
    set((state) => {
      const newItems = [...state.items];
      for (const product of products) {
        if (!newItems.find((i) => i.product.id === product.id)) {
          newItems.push({ product, quantity: 1 });
        }
      }
      return { items: newItems };
    });
  },

  clearCart: () => set({ items: [] }),
  openCart: () => set({ isOpen: true }),
  closeCart: () => set({ isOpen: false }),
  toggleCart: () => set((state) => ({ isOpen: !state.isOpen })),
}));

/* ─── Selectors ───────────────────────────────────────────────────────── */
export const useCartCount = () => useCartStore((s) => s.items.reduce((sum, i) => sum + i.quantity, 0));
export const useIsInCart = (productId: number) => useCartStore((s) => s.items.some((i) => i.product.id === productId));
