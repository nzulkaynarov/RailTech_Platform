// Refactored into ./admin-kyc/* (god-component split under the 500-line limit). This
// module is a thin re-export shim so existing import paths keep working:
//   import AdminKYCPage from './pages/AdminKYCPage'
//   import { AdminKYCPage } from './pages/AdminKYCPage'
export { AdminKYCPage } from './admin-kyc';
export { default } from './admin-kyc';
