/**
 * Карточка акта показывает то, что сервер уже отдаёт.
 *
 * Волна G2 сделала акт ДВУСТОРОННИМ: выпускает исполнитель, принимает заказчик, и API
 * возвращает обе подписи с именами (`issuer_signer_name` / `acceptor_signer_name`) плюс
 * адресные подсказки. Карточка при этом показывала ОДНО поле «Подписан» по legacy
 * `signed_at` — кто выпустил и кто принял, было не узнать, хотя данные приходили в том же
 * ответе. Тот же класс, что и весь аудит UI: сервер посчитал, интерфейс промолчал.
 *
 * Формулировки проверяются намеренно: клик без E-IMZO не является юридической подписью,
 * поэтому карточка говорит о согласовании и о том, ЧЕЙ сейчас ход, а не «подписано».
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, within } from '@testing-library/react';

import { ActsPage } from '../ActsPage';
import { actsApi, type Act } from '@/api/billingApi';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/api/billingApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/billingApi')>();
  return {
    ...actual,
    actsApi: { ...actual.actsApi, list: vi.fn(), sign: vi.fn(), reject: vi.fn() },
  };
});

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function makeAct(overrides: Partial<Act>): Act {
  return {
    id: 1,
    deal: 42,
    contract: null,
    invoice: 7,
    number: 'ACT-2026-00001',
    status: 'ISSUED',
    issued_at: '2026-07-01',
    signed_at: null,
    total_amount: '1120000',
    pdf_file: null,
    pdf_url: null,
    signed_file: null,
    signed_file_url: null,
    viewer_can_sign: false,
    viewer_can_reject: false,
    issuer_signer: 5,
    issuer_signer_name: 'Пётр Продавец',
    issuer_signed_at: '2026-07-01T10:00:00Z',
    acceptor_signer: null,
    acceptor_signer_name: null,
    acceptor_signed_at: null,
    rejection_reason: '',
    notes: '',
    created_at: '2026-07-01T10:00:00Z',
    updated_at: '2026-07-01T10:00:00Z',
    ...overrides,
  };
}

/** Открывает карточку первого акта в реестре. */
async function openCard() {
  fireEvent.click((await screen.findAllByText('ACT-2026-00001'))[0]);
  return screen.findByRole('dialog');
}

describe('карточка акта', () => {
  beforeEach(() => {
    vi.mocked(actsApi.list).mockReset();
  });

  it('называет выпустившего — имя приходило с сервера и терялось', async () => {
    vi.mocked(actsApi.list).mockResolvedValue([makeAct({})]);
    renderWithProviders(<ActsPage />);

    const card = await openCard();
    expect(within(card).getByText('Выпустил')).toBeInTheDocument();
    expect(within(card).getByText('Пётр Продавец')).toBeInTheDocument();
  });

  it('пока заказчик не принял — «Принял» честно пусто, а не выдумано', async () => {
    vi.mocked(actsApi.list).mockResolvedValue([makeAct({})]);
    renderWithProviders(<ActsPage />);

    const card = await openCard();
    const acceptedBlock = within(card).getByText('Принял').closest('div');
    expect(acceptedBlock).not.toBeNull();
    expect(within(acceptedBlock as HTMLElement).getByText('—')).toBeInTheDocument();
  });

  it('говорит, чей сейчас ход: у выпустившей стороны — ожидание заказчика', async () => {
    vi.mocked(actsApi.list).mockResolvedValue([makeAct({ viewer_can_sign: false })]);
    renderWithProviders(<ActsPage />);

    const card = await openCard();
    expect(within(card).getByText('Ожидает подтверждения заказчика')).toBeInTheDocument();
  });

  it('говорит, чей сейчас ход: у заказчика — ждёт именно его', async () => {
    vi.mocked(actsApi.list).mockResolvedValue([makeAct({ viewer_can_sign: true, viewer_can_reject: true })]);
    renderWithProviders(<ActsPage />);

    const card = await openCard();
    expect(within(card).getByText('Ждёт вашего подтверждения')).toBeInTheDocument();
  });

  it('согласованный обеими сторонами акт называет обоих и закрывает ход', async () => {
    vi.mocked(actsApi.list).mockResolvedValue([
      makeAct({
        status: 'SIGNED',
        acceptor_signer: 9,
        acceptor_signer_name: 'Иван Заказчик',
        acceptor_signed_at: '2026-07-05T12:00:00Z',
      }),
    ]);
    renderWithProviders(<ActsPage />);

    const card = await openCard();
    expect(within(card).getByText('Согласован обеими сторонами')).toBeInTheDocument();
    expect(within(card).getByText('Пётр Продавец')).toBeInTheDocument();
    expect(within(card).getByText('Иван Заказчик')).toBeInTheDocument();
  });

  it('возвращённый акт объясняет причину рядом со статусом', async () => {
    vi.mocked(actsApi.list).mockResolvedValue([
      makeAct({ status: 'DRAFT', rejection_reason: 'объём не совпадает с накладной' }),
    ]);
    renderWithProviders(<ActsPage />);

    const card = await openCard();
    expect(within(card).getByText(/объём не совпадает с накладной/)).toBeInTheDocument();
  });
});
