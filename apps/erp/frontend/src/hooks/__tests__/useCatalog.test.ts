import { describe, it, expect } from 'vitest';

/**
 * useCatalog hooks are thin wrappers around react-query + catalogApi.
 * Full integration tests require a running backend. Here we verify
 * that the module exports the expected hook functions (smoke test).
 */
describe('useCatalog exports', () => {
  it('should export all expected hooks', async () => {
    const mod = await import('../useCatalog');

    expect(typeof mod.useDomainTypes).toBe('function');
    expect(typeof mod.useProduct).toBe('function');
    expect(typeof mod.useProducts).toBe('function');
    expect(typeof mod.useProductsCount).toBe('function');
    expect(typeof mod.useCategories).toBe('function');
    expect(typeof mod.useManufacturers).toBe('function');
    expect(typeof mod.useEquipmentGroups).toBe('function');
    expect(typeof mod.useCreateProduct).toBe('function');
    expect(typeof mod.useUpdateProduct).toBe('function');
    expect(typeof mod.useDeleteProduct).toBe('function');
    expect(typeof mod.useCreateCategory).toBe('function');
    expect(typeof mod.useUpdateCategory).toBe('function');
    expect(typeof mod.useDeleteCategory).toBe('function');
    expect(typeof mod.useCreateEquipmentGroup).toBe('function');
    expect(typeof mod.useUpdateEquipmentGroup).toBe('function');
    expect(typeof mod.useDeleteEquipmentGroup).toBe('function');
    expect(typeof mod.useOffers).toBe('function');
    expect(typeof mod.useCreateOffer).toBe('function');
    expect(typeof mod.useUpdateOffer).toBe('function');
    expect(typeof mod.useDeleteOffer).toBe('function');
    expect(typeof mod.useBulkPublishProducts).toBe('function');
    expect(typeof mod.useProductStatuses).toBe('function');
    expect(typeof mod.useStockStatuses).toBe('function');
    expect(typeof mod.useUploadProductImage).toBe('function');
    expect(typeof mod.useDeleteProductImage).toBe('function');
    expect(typeof mod.useUploadProductDocument).toBe('function');
    expect(typeof mod.useDeleteProductDocument).toBe('function');
  });
});
