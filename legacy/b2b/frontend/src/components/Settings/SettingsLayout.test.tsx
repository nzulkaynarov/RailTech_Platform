import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';

import { SettingsLayout, type SettingsLayoutSection } from '@/components/Settings/SettingsLayout';
import { renderWithProviders } from '@/test/renderWithProviders';
import { useIsMobile } from '@/hooks/use-mobile';

// Управляем мобильным брейкпоинтом напрямую — jsdom-мок matchMedia всегда false.
vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: vi.fn(() => false),
  useMediaQuery: vi.fn(() => false),
}));

const SECTIONS: SettingsLayoutSection[] = [
  { key: 'profile', label: 'Личные данные', group: 'account' },
  { key: 'security', label: 'Безопасность', group: 'account' },
  { key: 'team', label: 'Команда', group: 'team' },
];

describe('SettingsLayout', () => {
  beforeEach(() => {
    vi.mocked(useIsMobile).mockReturnValue(false);
  });

  it('рендерит вертикальную навигацию секций и контент', () => {
    renderWithProviders(
      <SettingsLayout sections={SECTIONS} activeSection="profile" onSelectSection={() => {}}>
        <p>Содержимое секции</p>
      </SettingsLayout>,
    );
    expect(screen.getByRole('navigation')).toBeInTheDocument();
    for (const section of SECTIONS) {
      expect(screen.getByRole('button', { name: section.label })).toBeInTheDocument();
    }
    expect(screen.getByText('Содержимое секции')).toBeInTheDocument();
  });

  it('помечает активную секцию aria-current и вызывает onSelectSection по клику', () => {
    const onSelectSection = vi.fn();
    renderWithProviders(
      <SettingsLayout sections={SECTIONS} activeSection="security" onSelectSection={onSelectSection}>
        <p>Содержимое секции</p>
      </SettingsLayout>,
    );
    expect(screen.getByRole('button', { name: 'Безопасность' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('button', { name: 'Личные данные' })).not.toHaveAttribute('aria-current');

    fireEvent.click(screen.getByRole('button', { name: 'Команда' }));
    expect(onSelectSection).toHaveBeenCalledWith('team');
  });

  it('на мобильном сворачивается в Select с активной секцией', () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    renderWithProviders(
      <SettingsLayout sections={SECTIONS} activeSection="team" onSelectSection={() => {}}>
        <p>Содержимое секции</p>
      </SettingsLayout>,
    );
    // Вместо вертикального списка кнопок — combobox-триггер с текущей секцией.
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveTextContent('Команда');
    expect(screen.getByText('Содержимое секции')).toBeInTheDocument();
  });
});
