import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';

import { DealsKanban } from '../DealsKanban';
import type { Deal } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * Wave B2 (auto-claim) — for a SOLO seller «Взять в работу» is noise (a claim routes work
 * between teammates; with one member it routes nothing). The claim button must disappear from
 * the Kanban for a solo seller, while a multi-member company keeps it. Gating flows from
 * `capabilities.is_solo_team` via useIsSoloTeam; here we drive that hook directly.
 */

const soloRef = { value: false };
vi.mock('@/hooks/useCapabilities', () => ({
  useIsSoloTeam: () => soloRef.value,
  useHasCompanyPermission: () => true,
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const STAGES = [{ code: 'RFQ_OPEN', name: 'Открытый RFQ' }];
const DEALS: Deal[] = [
  { id: 1, title: 'Свежая заявка', stage_code: 'RFQ_OPEN', assigned_to: null, created_at: '2026-07-21T10:00:00Z' } as Deal,
];

describe('DealsKanban — solo-seller claim hidden (Wave B2 auto-claim)', () => {
  it('shows «Взять в работу» for a multi-member seller (not solo)', () => {
    soloRef.value = false;
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} />);
    expect(screen.getByRole('button', { name: 'Взять в работу' })).toBeInTheDocument();
  });

  it('hides «Взять в работу» for a solo seller', () => {
    soloRef.value = true;
    renderWithProviders(<DealsKanban deals={DEALS} stages={STAGES} />);
    expect(screen.queryByRole('button', { name: 'Взять в работу' })).not.toBeInTheDocument();
  });
});
