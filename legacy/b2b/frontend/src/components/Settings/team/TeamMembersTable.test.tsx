import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';

import { TeamMembersTable } from './TeamMembersTable';
import type { CompanyRole, User, UserMembership } from '@/api/accountsApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Presentational component — data arrives via props (the parent owns the queries),
// so no API mocking is needed here.

type MembershipFixture = UserMembership & { company_role?: number | null };

function makeMember(
  id: number,
  email: string,
  firstName: string,
  companyRoleId: number | null,
): User {
  const membership: MembershipFixture = {
    id: 100 + id,
    company: 1,
    company_role: companyRoleId,
  };
  return {
    id,
    username: email,
    email,
    first_name: firstName,
    last_name: '',
    phone: '',
    memberships: [membership],
  };
}

const ROLES: CompanyRole[] = [
  { id: 7, name: 'Менеджер КП', permissions: ['quote.build'], is_system: false, member_count: 1 } as CompanyRole,
];

const TEAM: User[] = [
  makeMember(1, 'owner@acme.uz', 'Владелец', 7),
  makeMember(2, 'sales@acme.uz', 'Продавец', null),
];

const baseProps = {
  team: TEAM,
  companyId: 1,
  companyRoles: ROLES,
  currentUserId: 1,
  onAssignRole: vi.fn(),
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

  it('shows read-only role badges without team.manage', () => {
    renderWithProviders(<TeamMembersTable {...baseProps} canManageTeam={false} />);
    // Assigned role resolves to its name; unassigned shows «Без роли». No editors.
    expect(screen.getAllByText('Менеджер КП').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Без роли').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('offers the role editor for OTHER members with team.manage', () => {
    renderWithProviders(<TeamMembersTable {...baseProps} canManageTeam />);
    // One combobox per representation (desktop + mobile) for the non-self member only;
    // self keeps the read-only badge («Менеджер КП»).
    expect(screen.getAllByRole('combobox').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Менеджер КП').length).toBeGreaterThanOrEqual(1);
  });

  it('shows the empty state for a team without members', () => {
    renderWithProviders(<TeamMembersTable {...baseProps} team={[]} canManageTeam />);
    expect(screen.getByText('Нет сотрудников')).toBeInTheDocument();
  });
});
