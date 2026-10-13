// Refactored into ./request-detail/* (god-component split, 500-line limit). This module is a
// thin re-export shim so existing import paths keep working:
//   import RequestDetailPage from './pages/RequestDetailPage'
//   import { RequestDetailPage } from './RequestDetailPage'
export { RequestDetailPage } from './request-detail';
export { default } from './request-detail';
