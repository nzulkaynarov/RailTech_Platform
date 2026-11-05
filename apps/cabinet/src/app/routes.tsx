import type { RouteObject } from 'react-router-dom';

import { AppShell } from '@/components/shell/AppShell';
import { NotFoundPage } from '@/pages/NotFoundPage';
import { ProfilePage } from '@/pages/ProfilePage';
import { ActsPage, ContractsPage, InvoicesPage } from '@/pages/billing';
import { CatalogItemPage, CatalogPage } from '@/pages/catalog';
import { CompanyPage, TeamPage } from '@/pages/company';
import { DealPage } from '@/pages/deal';
import { DeliveriesPage, DocumentsPage } from '@/pages/deliveries';
import { MessagesPage } from '@/pages/messages';
import { MyProductsPage } from '@/pages/myProducts';
import { QuoteDetailPage, QuotesPage } from '@/pages/quotes';
import { RequestDetailPage, RequestNewPage, RequestsPage } from '@/pages/requests';
import { LoginPage } from '@/pages/auth/LoginPage';
import { LoginSentPage } from '@/pages/auth/LoginSentPage';
import { MagicLinkPage } from '@/pages/auth/MagicLinkPage';
import { NewClientPage } from '@/pages/auth/NewClientPage';
import { VerifyPage } from '@/pages/verify/VerifyPage';
import { HomeRedirect, RequireModule, RequireSession, WebOnly } from './guards';
import { RootErrorPage } from './RootErrorPage';

/**
 * Маршруты Cabinet. Публичные (`/login`, `/login/sent`, `/login/code` — вход по коду из письма, `/new-client`) — только в вебе;
 * `/auth/magic#token=…` — ссылка из письма (токен во фрагменте; ссылок с токеном в пути на проде нет);
 * всё остальное — за сессией портала в оболочке. Непойманная ошибка любого маршрута —
 * `RootErrorPage` (корневой `errorElement`), а не белый экран.
 * Экраны разделов — ARCHITECTURE §5 (M2-CAB-02), по файлу на домен в `src/pages/`.
 */
export const routes: RouteObject[] = [
  {
    errorElement: <RootErrorPage />,
    children: [
      {
        element: <WebOnly />,
        children: [
          { path: '/login', element: <LoginPage /> },
          { path: '/login/sent', element: <LoginSentPage /> },
          { path: '/login/code', element: <LoginSentPage mode="code" /> },
          { path: '/new-client', element: <NewClientPage /> },
        ],
      },
      { path: '/auth/magic', element: <MagicLinkPage /> },
      { path: '/v/:code', element: <VerifyPage /> },
      {
        element: <RequireSession />,
        children: [
          {
            element: <AppShell />,
            children: [
              { index: true, path: '/', element: <HomeRedirect /> },
              {
                // Разделы за модулями сессии (`/me.modules`, ADR-0022)
                element: <RequireModule />,
                children: [
                  { path: '/my-products', element: <MyProductsPage /> },
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
                  { path: '/messages', element: <MessagesPage /> },
                  { path: '/company', element: <CompanyPage /> },
                  { path: '/team', element: <TeamPage /> },
                  { path: '/deals/:id', element: <DealPage /> },
                  { path: '/profile', element: <ProfilePage /> },
                  { path: '*', element: <NotFoundPage /> },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
];
