import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { TeamMembersTable } from './TeamMembersTable';
import type { CompanyRole, User, UserMembership } from '@/api/accountsApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Presentational component — data arrives via props (the parent owns the queries),
// so no API mocking is needed here.

function makeMember(
  id: number,
  email: string,
  firstName: string,
  roleIds: number[],
  isActive = true,
): User {
  const membership: UserMembership = {
    id: 100 + id,
    company: 1,
    company_roles: roleIds,
  };
  return {
    id,
    username: email,
    email,
    first_name: firstName,
    last_name: '',
    phone: '',
    is_active: isActive,
    memberships: [membership],
  };
}

const ROLES: CompanyRole[] = [
  { id: 7, code: '', name: 'Менеджер КП', permissions: ['quote.build'], is_system: false, member_count: 1 },
  { id: 8, code: 'FINANCE', name: 'Финансы', permissions: ['finance.invoice'], is_system: true, member_count: 1 },
  { id: 9, code: 'HEAD', name: 'Руководитель', permissions: ['team.manage'], is_system: true, member_count: 0 },
];

const TEAM: User[] = [
  makeMember(1, 'owner@acme.uz', 'Владелец', [7, 8]),
  makeMember(2, 'sales@acme.uz', 'Продавец', []),
];

const baseProps = {
  team: TEAM,
  companyId: 1,
  companyRoles: ROLES,
  currentUserId: 1,
  onAssignRoles: vi.fn(),
  assignPending: false,
};

describe('TeamMembersTable', () => {
  // ResponsiveDataTable renders BOTH a desktop table and a mobile stacked list
  // (CSS-hidden, both in the DOM) — row content appears twice, so query with *All*.

  it('renders members with the self marker', () => {
    renderWithProviders(<TeamMembersTable {...baseProps} canManageTeam={false} />);
    expect(screen.getAllByText('Владелец').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('sales@acme.uz').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('(Это вы)').length).toBeGreaterThanOrEqual(1);
  });

  it('shows every role of a member as a badge, read-only without team.manage (M1-ERP-05)', () => {
    renderWithProviders(<TeamMembersTable {...baseProps} canManageTeam={false} />);
    // Несколько ролей — несколько бейджей; системная роль — имя по коду из i18n; без ролей — «Без ролей».
    expect(screen.getAllByText('Менеджер КП').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Финансы').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Без ролей').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByLabelText(/Выбрать роли/)).not.toBeInTheDocument();
  });

  it('offers the multi-role picker for OTHER members with team.manage', () => {
    renderWithProviders(<TeamMembersTable {...baseProps} canManageTeam />);
    // Picker only for the non-self member (desktop + mobile representations); self keeps badges.
    expect(screen.getAllByLabelText('Выбрать роли: Продавец').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByLabelText('Выбрать роли: Владелец')).not.toBeInTheDocument();
  });

  it('toggling a role sends the WHOLE new set of role ids', async () => {
    const onAssignRoles = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<TeamMembersTable {...baseProps} canManageTeam onAssignRoles={onAssignRoles} />);
    await user.click(screen.getAllByLabelText('Выбрать роли: Продавец')[0]);
    await user.click(await screen.findByRole('menuitemcheckbox', { name: 'Руководитель' }));
    expect(onAssignRoles).toHaveBeenCalledWith(102, [9]);
  });

  it('shows the empty state for a team without members', () => {
    renderWithProviders(<TeamMembersTable {...baseProps} team={[]} canManageTeam />);
    expect(screen.getByText('Нет сотрудников')).toBeInTheDocument();
  });

  it('renders the REAL status — active and disabled (P8)', () => {
    const team: User[] = [
      makeMember(1, 'owner@acme.uz', 'Владелец', [7], true),
      makeMember(2, 'off@acme.uz', 'Отключённый', [], false),
    ];
    renderWithProviders(
      <TeamMembersTable {...baseProps} team={team} canManageTeam={false} />,
    );
    expect(screen.getAllByText('Активен').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Отключён').length).toBeGreaterThanOrEqual(1);
  });

  it('offers deactivate + remove actions for OTHER members with team.manage (P2)', () => {
    renderWithProviders(<TeamMembersTable {...baseProps} canManageTeam />);
    // Non-self member (sales) gets both actions; self (owner) does not.
    expect(screen.getAllByLabelText('Деактивировать').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByLabelText('Удалить из команды').length).toBeGreaterThanOrEqual(1);
  });

  it('hides member actions without team.manage', () => {
    renderWithProviders(<TeamMembersTable {...baseProps} canManageTeam={false} />);
    expect(screen.queryByLabelText('Удалить из команды')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Деактивировать')).not.toBeInTheDocument();
  });
});
