/**
 * Settings Hub layout (spec §2.3) — вертикальная навигация секций + область контента.
 *
 * НЕ shadcn <Sidebar> (он зарезервирован за двумя shells, Rule 4) — вертикальный список
 * Button variant="ghost" с активным состоянием через семантические токены. На мобильном
 * (useIsMobile) список сворачивается в Select. Ширина — только grid-утилиты Tailwind (§2.4);
 * контентная область full-width, капы ширины отдельных reading-форм — внутри секций.
 */
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useIsMobile } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';

export interface SettingsLayoutSection {
  key: string;
  label: string;
  /** Ключ группы (S2) — секции в сайдбаре кластеризуются под заголовком t(`settings.groups.<group>`). */
  group: string;
}

interface SettingsLayoutProps {
  sections: SettingsLayoutSection[];
  activeSection: string;
  onSelectSection: (key: string) => void;
  children: ReactNode;
}

export function SettingsLayout({ sections, activeSection, onSelectSection, children }: SettingsLayoutProps) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();

  if (isMobile) {
    return (
      <div className="flex flex-col gap-4">
        <Select value={activeSection} onValueChange={onSelectSection}>
          <SelectTrigger className="w-full" aria-label={t('settings.title')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {sections.map((section) => (
              <SelectItem key={section.key} value={section.key}>
                {section.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="min-w-0">{children}</div>
      </div>
    );
  }

  // S2 — группируем секции по group, сохраняя исходный порядок групп (первое появление).
  const groupOrder: string[] = [];
  const grouped = new Map<string, SettingsLayoutSection[]>();
  for (const section of sections) {
    if (!grouped.has(section.group)) {
      grouped.set(section.group, []);
      groupOrder.push(section.group);
    }
    grouped.get(section.group)!.push(section);
  }

  return (
    <div className="grid gap-6 md:grid-cols-[220px_1fr]">
      <nav aria-label={t('settings.title')} className="flex flex-col gap-4">
        {groupOrder.map((group) => (
          <div key={group} className="flex flex-col gap-1">
            <p className="px-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t(`settings.groups.${group}`)}
            </p>
            {grouped.get(group)!.map((section) => {
              const isActive = section.key === activeSection;
              return (
                <Button
                  key={section.key}
                  variant="ghost"
                  aria-current={isActive ? 'page' : undefined}
                  className={cn(
                    'justify-start',
                    isActive ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground',
                  )}
                  onClick={() => onSelectSection(section.key)}
                >
                  {section.label}
                </Button>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
