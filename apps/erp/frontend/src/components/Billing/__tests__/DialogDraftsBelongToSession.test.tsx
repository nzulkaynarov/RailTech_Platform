/**
 * Черновик диалога принадлежит СЕССИИ ОТКРЫТИЯ и КОНКРЕТНОЙ записи.
 *
 * Прогон глазами 19-08 показал целый класс тихих дефектов: текст, набранный в диалоге и
 * брошенный без отправки, всплывал при следующем открытии — в том числе для ДРУГОГО документа —
 * и уходил на сервер. Это не косметика: причина возврата дописывается исполнителю в акт,
 * основание аннулирования — в карточку договора, а в платеже вместе с текстом уезжал ещё и
 * файл-скан «подтверждение оплаты» от прошлого счёта.
 *
 * Тесты держат само правило, а не конкретный экран: пустое поле при новом открытии и при смене
 * записи. Ломается это молча — API отвечает 200, тесты страниц зелёные, видит только человек.
 */

import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { RejectActDialog } from '../RejectActDialog';

const noop = async () => {};

describe('RejectActDialog — причина принадлежит акту и открытию', () => {
  it('повторное открытие того же акта начинается с пустого поля', () => {
    const { rerender } = renderWithProviders(
      <RejectActDialog actNumber="ACT-1" open onOpenChange={() => {}} onConfirm={noop} />,
    );

    const field = screen.getByRole('textbox');
    fireEvent.change(field, { target: { value: 'брошено без отправки' } });
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('брошено без отправки');

    rerender(<RejectActDialog actNumber="ACT-1" open={false} onOpenChange={() => {}} onConfirm={noop} />);
    rerender(<RejectActDialog actNumber="ACT-1" open onOpenChange={() => {}} onConfirm={noop} />);

    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
  });

  it('смена акта БЕЗ закрытия диалога тоже очищает поле', () => {
    // Именно так дефект и стрелял: страница держит диалог смонтированным и меняет только номер.
    const { rerender } = renderWithProviders(
      <RejectActDialog actNumber="ACT-1" open onOpenChange={() => {}} onConfirm={noop} />,
    );
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'причина про ACT-1' } });

    rerender(<RejectActDialog actNumber="ACT-2" open onOpenChange={() => {}} onConfirm={noop} />);

    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
  });

  it('отправляется ровно то, что человек набрал в ЭТОМ открытии', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderWithProviders(
      <RejectActDialog actNumber="ACT-1" open onOpenChange={() => {}} onConfirm={onConfirm} />,
    );
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'чужая причина' } });

    rerender(<RejectActDialog actNumber="ACT-2" open onOpenChange={() => {}} onConfirm={onConfirm} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'своя причина про ACT-2' } });

    const confirm = screen.getAllByRole('button').find((b) => !/отмен|cancel/i.test(b.textContent ?? ''));
    fireEvent.click(confirm as HTMLElement);

    await vi.waitFor(() => expect(onConfirm).toHaveBeenCalled());
    expect(onConfirm).toHaveBeenCalledWith('своя причина про ACT-2');
  });
});
