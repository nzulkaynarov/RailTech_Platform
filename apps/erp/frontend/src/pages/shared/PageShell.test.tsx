import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { PageShell } from './PageShell';

/**
 * Плитка шапки не выдаёт сбой загрузки за факт (находка 88 прогона 20-08).
 *
 * Замер: запрос списка компаний заблокирован. В теле карточки честно написано «Не удалось
 * загрузить данные» с кнопкой «Повторить», а плашки НАД ней уверенно показывали «Всего
 * компаний 0 · Ожидание 0 · Верифицированы 0 · Партнёры 0» — при том что в сайдбаре рядом
 * висел красный бейдж «1». Беглый взгляд на верх экрана — самый частый способ снять статус,
 * и он давал ложное «на проверке никого нет».
 *
 * Эталон Odoo O-SAMPLE: сбой показывают сбоем, а не пустотой.
 */

const STATS = [
  { label: 'Всего компаний', value: '52' },
  { label: 'Не подтверждены', value: '19' },
];

function shell(props: Partial<React.ComponentProps<typeof PageShell>> = {}) {
  return (
    <PageShell title="Компании" description="Реестр" icon={<span />} stats={STATS} {...props}>
      <div>тело</div>
    </PageShell>
  );
}

describe('плитки PageShell', () => {
  it('при нормальной загрузке печатают числа', () => {
    renderWithProviders(shell());

    expect(screen.getByText('52')).toBeInTheDocument();
    expect(screen.getByText('19')).toBeInTheDocument();
  });

  it('при ошибке загрузки НЕ печатают нули и не печатают старые числа', () => {
    renderWithProviders(shell({ statsError: true }));

    expect(screen.queryByText('52')).not.toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
    // Подписи остаются: человек видит, ЧТО именно неизвестно.
    expect(screen.getByText('Всего компаний')).toBeInTheDocument();
    expect(screen.getAllByText('—')).toHaveLength(STATS.length);
  });

  it('до первого ответа число не выдумывается', () => {
    renderWithProviders(shell({ statsLoading: true }));

    expect(screen.queryByText('52')).not.toBeInTheDocument();
    expect(screen.getByText('Всего компаний')).toBeInTheDocument();
  });

  it('ошибка важнее загрузки: одновременно оба признака дают прочерк', () => {
    renderWithProviders(shell({ statsError: true, statsLoading: true }));

    expect(screen.getAllByText('—')).toHaveLength(STATS.length);
  });
});
