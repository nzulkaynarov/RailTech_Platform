/**
 * Раздача возможностей участника — то, что модель вменяет администратору компании.
 *
 * `CompanyMember.can_sell` / `can_buy` (ADR-0002) распределяет администратор, эндпоинт
 * `update-member-capabilities` и хук `useUpdateMemberCapabilities` для этого есть — но вызвать
 * их было НЕОТКУДА (аудит UI 2026-07-30, §3.2). Паттерн размещения — Odoo: права редактируются
 * на записи самого пользователя, а не на отдельном экране.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { TeamMembersTable } from './TeamMembersTable';
import type { CompanyRole, User, UserMembership } from '@/api/accountsApi';
import { accountsApi } from '@/api/accountsApi';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/api/accountsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/accountsApi')>();
  return {
    ...actual,
    accountsApi: { ...actual.accountsApi, updateMemberCapabilities: vi.fn() },
  };
});

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

type MembershipFixture = UserMembership & { company_role?: number | null };

function makeMember(id: number, email: string, name: string, caps: { can_sell?: boolean; can_buy?: boolean }): User {
  const membership: MembershipFixture = { id: 100 + id, company: 1, company_role: null, ...caps };
  return {
    id,
    username: email,
    email,
    first_name: name,
    last_name: '',
    phone: '',
    is_active: true,
    memberships: [membership],
  };
}

const ROLES: CompanyRole[] = [];

const baseProps = {
  companyId: 1,
  companyRoles: ROLES,
  currentUserId: 1,
  onAssignRole: vi.fn(),
  assignPending: false,
};

/** Строка участника (десктопная таблица; мобильный список дублирует контент). */
function rowOf(name: string): HTMLElement {
  const cell = screen.getAllByText(name)[0];
  const row = cell.closest('tr') ?? cell.closest('[data-slot="card"]');
  if (!row) throw new Error(`нет строки для «${name}»`);
  return row as HTMLElement;
}

describe('возможности участника', () => {
  beforeEach(() => {
    vi.mocked(accountsApi.updateMemberCapabilities).mockReset().mockResolvedValue({
      id: 102, user_id: 2, can_sell: false, can_buy: true,
    } as never);
  });

  it('администратор переключает права, и уходит запрос по ЭТОМУ участнику', async () => {
    const team = [
      makeMember(1, 'admin@acme.uz', 'Администратор', { can_sell: true, can_buy: true }),
      makeMember(2, 'sales@acme.uz', 'Продавец', { can_sell: true, can_buy: true }),
    ];
    renderWithProviders(<TeamMembersTable {...baseProps} team={team} canManageTeam />);

    const sellToggle = within(rowOf('Продавец')).getByRole('switch', { name: 'Продажи' });
    expect(sellToggle).toBeChecked();
    fireEvent.click(sellToggle);

    await waitFor(() =>
      expect(accountsApi.updateMemberCapabilities).toHaveBeenCalledWith(1, {
        member_id: 102,
        can_sell: false,
        can_buy: undefined,
      }),
    );
  });

  it('снятое право отражается выключенным переключателем, а не молчанием', () => {
    const team = [
      makeMember(1, 'admin@acme.uz', 'Администратор', { can_sell: true, can_buy: true }),
      makeMember(2, 'buyer@acme.uz', 'Закупщик', { can_sell: false, can_buy: true }),
    ];
    renderWithProviders(<TeamMembersTable {...baseProps} team={team} canManageTeam />);

    const row = rowOf('Закупщик');
    expect(within(row).getByRole('switch', { name: 'Продажи' })).not.toBeChecked();
    expect(within(row).getByRole('switch', { name: 'Закупки' })).toBeChecked();
  });

  it('без права управлять командой права видны, но не редактируются', () => {
    const team = [makeMember(2, 'sales@acme.uz', 'Продавец', { can_sell: true, can_buy: false })];
    renderWithProviders(<TeamMembersTable {...baseProps} team={team} canManageTeam={false} />);

    expect(screen.queryByRole('switch', { name: 'Продажи' })).not.toBeInTheDocument();
    // Читаемая сводка вместо переключателей — участник видит расклад, менять не может.
    expect(screen.getAllByText('Продажи')[0]).toBeInTheDocument();
  });

  it('свои собственные права администратор не переключает', () => {
    // Сняв с себя продажи, он потерял бы доступ к собственной воронке и чинил бы это через
    // другого администратора. Себя строка показывает только сводкой.
    const team = [makeMember(1, 'admin@acme.uz', 'Администратор', { can_sell: true, can_buy: true })];
    renderWithProviders(<TeamMembersTable {...baseProps} team={team} canManageTeam />);

    expect(screen.queryByRole('switch', { name: 'Продажи' })).not.toBeInTheDocument();
  });
});
