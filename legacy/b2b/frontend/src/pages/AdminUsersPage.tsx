// Refactored into ./admin-users/* (god-component split, 500-line limit). This module is a
// thin re-export shim so existing import paths keep working:
//   import AdminUsersPage from './pages/AdminUsersPage'
//   import { AdminUsersPage } from './AdminUsersPage'
export { AdminUsersPage } from './admin-users';
export { default } from './admin-users';
