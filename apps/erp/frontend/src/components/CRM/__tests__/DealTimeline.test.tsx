import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';

import { DealTimeline } from '../DealTimeline';
import { crmApi, type TimelineEntry } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Mock at the API-client layer: the real useDealTimeline react-query hook runs
// against this mock (never the network).
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, getTimeline: vi.fn() },
  };
});

function makeEntry(overrides: Partial<TimelineEntry> & { id: number }): TimelineEntry {
  return {
    action: '',
    detail: '',
    level: 'INFO',
    timestamp: '2026-07-10T10:00:00Z',
    user_name: '',
    entity_type: 'deal',
    entity_id: 25,
    deal_id: 25,
    company_id: null,
    contact_id: null,
    ...overrides,
  };
}

describe('DealTimeline', () => {
  beforeEach(() => {
    vi.mocked(crmApi.getTimeline).mockReset();
  });

  it('renders a structured event localized with its params', async () => {
    vi.mocked(crmApi.getTimeline).mockResolvedValue([
      makeEntry({
        id: 1,
        // Backend still stores the RU prose in `action`; the client must prefer the code.
        action: 'RAW ACTION SHOULD NOT SHOW',
        event_code: 'deal.created',
        event_params: { actor_email: 'client@x.uz', deal_id: 25, company_name: 'ООО Магистраль' },
      }),
    ]);

    renderWithProviders(<DealTimeline dealId={25} />);

    // Title from activity.deal.created.title (ru.json).
    expect(await screen.findByText('Сделка создана')).toBeInTheDocument();
    // Detail interpolates event_params into activity.deal.created.detail.
    expect(
      screen.getByText(
        'Пользователь client@x.uz инициировал новую сделку #25 для компании ООО Магистраль',
      ),
    ).toBeInTheDocument();
    // The raw RU `action` must NOT leak through when a code+key exist.
    expect(screen.queryByText('RAW ACTION SHOULD NOT SHOW')).not.toBeInTheDocument();
  });

  it('falls back to the raw action/detail for a legacy row without an event_code', async () => {
    vi.mocked(crmApi.getTimeline).mockResolvedValue([
      makeEntry({
        id: 2,
        action: 'Произвольное историческое событие',
        detail: 'Подробность из БД',
      }),
    ]);

    renderWithProviders(<DealTimeline dealId={25} />);

    expect(await screen.findByText('Произвольное историческое событие')).toBeInTheDocument();
    expect(screen.getByText('Подробность из БД')).toBeInTheDocument();
  });

  it('falls back to the raw action when the event_code has no matching key', async () => {
    vi.mocked(crmApi.getTimeline).mockResolvedValue([
      makeEntry({
        id: 3,
        action: 'Force: стадия изменена',
        event_code: 'admin.unknown_code',
        event_params: { foo: 'bar' },
      }),
    ]);

    renderWithProviders(<DealTimeline dealId={25} />);

    expect(await screen.findByText('Force: стадия изменена')).toBeInTheDocument();
  });
});
