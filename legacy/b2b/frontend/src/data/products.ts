// Legacy Product type used by frontend components during migration period
export interface Product {
  id: string;
  name: string;
  article: string;
  gost: string;
  uom: string;
  quantity: number;
  domain: 'RAILWAY_MACHINERY' | 'GENERAL_GOODS' | 'SERVICES';
  category: string;
  status: 'in_stock' | 'to_order' | 'sourcing' | 'inactive';
  manufacturer: string;
  addedDate: string;
  ownerCompanyId: string;
  partnerVisible: boolean;
  approvedSellers?: string[];
  basePriceFCA?: number;
  description?: string;
  materialId?: string;
  iso?: string;
  packageQuantity?: number;
  images?: string[];
  similarProducts?: string[];
  matchingTools?: number;
  specifications?: Record<string, string>;
  prevQuantity?: number;
}

// Product data is now loaded from the backend API.
// This empty array is kept for backwards compatibility during migration.
// Use catalogApi.getProducts() to fetch from backend.
export const products: Product[] = [];

export const statusLabels: Record<string, string> = {
  in_stock: 'В наличии',
  to_order: 'Под заказ',
  sourcing: 'Поиск',
  inactive: 'Неактивен',
};

export const domainLabels: Record<string, string> = {
  RAILWAY_MACHINERY: 'ЖД и Техника',
  GENERAL_GOODS: 'Общие товары',
  SERVICES: 'Услуги',
};

// Re-export API product type for new components that need it
export type { Product as ApiProduct } from '../api/catalogApi';
