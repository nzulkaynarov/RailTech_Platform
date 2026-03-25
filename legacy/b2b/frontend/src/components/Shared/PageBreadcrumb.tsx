import * as React from 'react';
import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Home } from 'lucide-react';

export interface BreadcrumbSegment {
  label: string;
  pageId?: string; // if clickable
}

interface PageBreadcrumbProps {
  segments: BreadcrumbSegment[];
  onNavigate: (pageId: string) => void;
}

const pageLabels: Record<string, string> = {
  dashboard: 'Дашборд',
  products: 'Каталог',
  'my-requests': 'Мои заявки',
  'request-detail': 'Заявка',
  'crm-deals': 'Сделки',
  'crm-quotes': 'Котировки',
  'crm-clients': 'Клиенты',
  'sourcing-requests': 'Заявки на снабжение',
  'sourcing-import': 'Импорт',
  'sourcing-match': 'Sourcing Hub',
  'production-orders': 'Заказы на производство',
  'production-schedule': 'График производства',
  analytics: 'Аналитика',
  categories: 'Категории',
  'equipment-groups': 'Группы техники',
  integrations: 'Интеграции',
  help: 'Помощь',
  profile: 'Профиль',
  settings: 'Настройки',
  'my-documents': 'Документы',
  'admin-users': 'Пользователи',
  logistics: 'Логистика',
  'purchase-templates': 'Шаблоны закупок',
};

export function getPageLabel(pageId: string): string {
  return pageLabels[pageId] ?? pageId;
}

export function PageBreadcrumb({ segments, onNavigate }: PageBreadcrumbProps) {
  if (segments.length === 0) return null;

  return (
    <Breadcrumb className="mb-4">
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbLink
            className="cursor-pointer flex items-center gap-1"
            onClick={() => onNavigate('dashboard')}
          >
            <Home className="h-3.5 w-3.5" />
          </BreadcrumbLink>
        </BreadcrumbItem>
        {segments.map((seg, i) => (
          <React.Fragment key={i}>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              {i < segments.length - 1 && seg.pageId ? (
                <BreadcrumbLink
                  className="cursor-pointer"
                  onClick={() => onNavigate(seg.pageId!)}
                >
                  {seg.label}
                </BreadcrumbLink>
              ) : (
                <BreadcrumbPage>{seg.label}</BreadcrumbPage>
              )}
            </BreadcrumbItem>
          </React.Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
