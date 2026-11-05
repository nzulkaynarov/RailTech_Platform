import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'vitest-axe';

import { renderApp } from '@/test/render';
import * as fixtures from '@/mocks/fixtures';

describe('публичная проверка документа (/v/:code)', () => {
  it('валидный документ: отображает бейдж подлинности, реквизиты, подписанта и хеш', async () => {
    const { container } = renderApp('/v/doc-verify-12345');

    expect(await screen.findByTestId('status-valid')).toBeInTheDocument();
    expect(screen.getByText('Подлинность подтверждена')).toBeInTheDocument();
    expect(screen.getByText('Официальный документ выпущен и подписан в RailTech Platform')).toBeInTheDocument();

    expect(screen.getByText('ИСХ-042/26')).toBeInTheDocument();
    expect(screen.getByText('OOO «RailTech»')).toBeInTheDocument();
    expect(screen.getByText('Иванов Иван Иванович')).toBeInTheDocument();
    expect(screen.getByText('Генеральный директор')).toBeInTheDocument();
    expect(screen.getByText('на основании Устава')).toBeInTheDocument();
    expect(screen.getByText(fixtures.mockDocumentVerification.sha256_hash!)).toBeInTheDocument();

    // axe audit
    expect((await axe(container)).violations).toEqual([]);
  });

  it('отозванный документ: отображает предупреждение об отзыве и причину', async () => {
    renderApp('/v/revoked');

    expect(await screen.findByTestId('status-revoked')).toBeInTheDocument();
    expect(screen.getByText('Документ отозван')).toBeInTheDocument();
    expect(screen.getByText('Этот документ был отозван и утратил юридическую силу')).toBeInTheDocument();
    expect(
      screen.getByText(/Отозван в связи с отменой доверенности/),
    ).toBeInTheDocument();
  });

  it('неизвестный код: 404 экран «Документ не найден»', async () => {
    const { container } = renderApp('/v/unknown-code-999');

    expect(await screen.findByText('Документ не найден')).toBeInTheDocument();
    expect(
      screen.getByText(/Документ с кодом «unknown-code-999» не найден в системе/),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /На главную/ })).toHaveAttribute('href', '/');

    expect((await axe(container)).violations).toEqual([]);
  });

  it('превышение лимита: 429 экран «Слишком много запросов»', async () => {
    renderApp('/v/rate-limited');

    expect(await screen.findByText('Слишком много запросов')).toBeInTheDocument();
    expect(screen.getByText(/Превышен лимит запросов на проверку документов/)).toBeInTheDocument();
  });

  it('проверка целостности файла: вычисление SHA-256 и проверка совпадения', async () => {
    const user = userEvent.setup();
    renderApp('/v/doc-verify-12345');

    await screen.findByTestId('status-valid');

    // Create a dummy file with specific content
    const content = 'RailTech Official Document Content';
    const file = new File([content], 'letter.pdf', { type: 'application/pdf' });

    // Calculate actual hash of this content
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    const expectedHash = Array.from(new Uint8Array(hashBuffer))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');

    const input = document.getElementById('verify-file') as HTMLInputElement;
    expect(input).toBeInTheDocument();

    // First: file that does not match the fixture's sha256_hash
    await user.upload(input, file);

    const mismatchBox = await screen.findByTestId('hash-result');
    expect(mismatchBox).toBeInTheDocument();
    expect(screen.getByText('Контрольная сумма НЕ совпадает! Файл повреждён или подвергся модификации.')).toBeInTheDocument();
    expect(screen.getByText(expectedHash)).toBeInTheDocument();
  });

  it('копирование хеша в буфер обмена', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    const original = navigator.clipboard;
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });

    try {
      renderApp('/v/doc-verify-12345');

      await screen.findByTestId('status-valid');
      const copyBtn = screen.getByRole('button', { name: /Скопировать хеш/ });
      await user.click(copyBtn);

      expect(writeText).toHaveBeenCalledWith(fixtures.mockDocumentVerification.sha256_hash);
      expect(await screen.findByText('Скопировано')).toBeInTheDocument();
    } finally {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: original });
    }
  });
});
