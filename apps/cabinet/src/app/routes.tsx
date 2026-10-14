import type { RouteObject } from 'react-router-dom';

import { AppShell } from '@/components/shell/AppShell';
import { NotFoundPage } from '@/pages/NotFoundPage';
import { ProfilePage } from '@/pages/ProfilePage';
import {
  ActsPage,
  CatalogItemPage,
  CatalogPage,
  CompanyPage,
  ContractsPage,
  DealPage,
  DeliveriesPage,
  DocumentsPage,
  InvoicesPage,
  QuoteDetailPage,
  QuotesPage,
  RequestDetailPage,
  RequestNewPage,
  RequestsPage,
  TeamPage,
} from '@/pages/SectionPages';
import { LoginPage } from '@/pages/auth/LoginPage';
import { LoginSentPage } from '@/pages/auth/LoginSentPage';
import { MagicLinkPage } from '@/pages/auth/MagicLinkPage';
import { NewClientPage } from '@/pages/auth/NewClientPage';
import { HomeRedirect, RequireSession, WebOnly } from './guards';

/**
 * Маршруты Cabinet. Публичные (`/login`, `/login/sent`, `/new-client`) — только в вебе;
 * `/auth/magic/:token` — ссылка из письма; всё остальное — за сессией портала в оболочке.
 * Экраны разделов — ARCHITECTURE §5 (данные — M2-CAB-02).
 */
export const routes: RouteObject[] = [
  {
    element: <WebOnly />,
    children: [
      { path: '/login', element: <LoginPage /> },
      { path: '/login/sent', element: <LoginSentPage /> },
      { path: '/new-client', element: <NewClientPage /> },
    ],
  },
  { path: '/auth/magic/:token', element: <MagicLinkPage /> },
  {
    element: <RequireSession />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, path: '/', element: <HomeRedirect /> },
          { path: '/requests', element: <RequestsPage /> },
          { path: '/requests/new', element: <RequestNewPage /> },
          { path: '/requests/:id', element: <RequestDetailPage /> },
          { path: '/quotes', element: <QuotesPage /> },
          { path: '/quotes/:id', element: <QuoteDetailPage /> },
          { path: '/contracts', element: <ContractsPage /> },
          { path: '/invoices', element: <InvoicesPage /> },
          { path: '/acts', element: <ActsPage /> },
          { path: '/deliveries', element: <DeliveriesPage /> },
          { path: '/documents', element: <DocumentsPage /> },
          { path: '/catalog', element: <CatalogPage /> },
          { path: '/catalog/:id', element: <CatalogItemPage /> },
          { path: '/company', element: <CompanyPage /> },
          { path: '/team', element: <TeamPage /> },
          { path: '/deals/:id', element: <DealPage /> },
          { path: '/profile', element: <ProfilePage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
