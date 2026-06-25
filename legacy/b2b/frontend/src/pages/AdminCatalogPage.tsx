// Refactored into ./admin-catalog/* (F4.x god-component split). This module is a
// thin re-export shim so existing import paths keep working:
//   import AdminCatalogPage from './pages/AdminCatalogPage'
//   import { ProductFormSheet } from './AdminCatalogPage'
export { AdminCatalogPage, ProductFormSheet } from './admin-catalog';
export { default } from './admin-catalog';
