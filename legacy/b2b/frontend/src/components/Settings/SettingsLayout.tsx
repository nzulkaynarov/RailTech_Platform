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

  return (
    <div className="grid gap-6 md:grid-cols-[220px_1fr]">
      <nav aria-label={t('settings.title')} className="flex flex-col gap-1">
        {sections.map((section) => {
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
      </nav>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
