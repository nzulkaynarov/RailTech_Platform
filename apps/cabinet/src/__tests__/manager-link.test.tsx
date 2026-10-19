import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { botLink, managerLink } from '@/app/links';
import { asMiniApp, renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';

/**
 * «Написать менеджеру» (M2-CAB-03): `t.me/<бот>?start=deal_<id>`. DoD — ссылка содержит контекст
 * сделки. Имя бота в тестах — `railtech_test_bot` (vitest.config.ts).
 */
const BOT = 'https://t.me/railtech_test_bot';
/** Экран сделки собирается из семи списков портала — под параллельной нагрузкой дольше 1 с. */
const LOADED = { timeout: 5000 };

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('ссылки на бота', () => {
  it('managerLink: контекст сделки в параметре start', () => {
    expect(managerLink(42)).toBe(`${BOT}?start=deal_42`);
    expect(new URL(managerLink(7)!).searchParams.get('start')).toBe('deal_7');
  });

  it('без сделки — чат с ботом без контекста, а не битый deal_undefined', () => {
    expect(managerLink(undefined)).toBe(BOT);
    expect(managerLink(null)).toBe(BOT);
    expect(managerLink(Number.NaN)).toBe(BOT);
  });

  it('имя бота с @ принимается; пустое имя — ссылок нет', () => {
    vi.stubEnv('VITE_BOT_USERNAME', '@railtech_test_bot');
    expect(botLink('web')).toBe(`${BOT}?start=web`);
    vi.stubEnv('VITE_BOT_USERNAME', '');
    expect(botLink('web')).toBeNull();
    expect(managerLink(42)).toBeNull();
  });
});

describe('«Написать менеджеру» на экранах', () => {
  it('сделка: кнопка в шапке ведёт в бота с deal_<id>, в вебе — новая вкладка', async () => {
    signedIn();
    renderApp('/deals/35');
    const link = await screen.findByRole('link', { name: 'Написать менеджеру' }, LOADED);
    expect(link).toHaveAttribute('href', `${BOT}?start=deal_35`);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    await expectNoAxeViolations();
  });

  it('карточка КП: сделка этого КП', async () => {
    signedIn();
    renderApp('/quotes/301');
    await heading(/KP-2026-0042/);
    const link = screen.getByRole('link', { name: 'Написать менеджеру о КП KP-2026-0042' });
    expect(link).toHaveAttribute('href', `${BOT}?start=deal_42`);
    expect(link).toHaveTextContent('Написать менеджеру');
  });

  it.each([
    ['/contracts', 'Договоры', 'Написать менеджеру о договоре D-2026-0048', 48],
    ['/invoices', 'Счета', 'Написать менеджеру о счёте S-2026-0124', 29],
    ['/acts', 'Акты', 'Написать менеджеру об акте A-2026-0090', 35],
  ])('%s: в строке документа — сделка документа', async (path, title, name, dealId) => {
    signedIn();
    renderApp(path);
    await heading(title);
    expect(await screen.findByRole('link', { name })).toHaveAttribute('href', `${BOT}?start=deal_${dealId}`);
    await expectNoAxeViolations();
  });

  it('поставки: в шапке каждой сделки своя ссылка', async () => {
    signedIn();
    renderApp('/deliveries');
    await heading('Поставки');
    const links = await screen.findAllByRole('link', { name: /^Написать менеджеру о сделке № D-\d+$/ });
    expect(links.length).toBeGreaterThan(1);
    for (const link of links) {
      const id = link.getAttribute('aria-label')!.match(/D-(\d+)/)![1];
      expect(link).toHaveAttribute('href', `${BOT}?start=deal_${id}`);
    }
    await expectNoAxeViolations();
  });

  it('имя бота не задано — кнопок нет (не битая ссылка)', async () => {
    vi.stubEnv('VITE_BOT_USERNAME', '');
    signedIn();
    renderApp('/deals/35');
    await screen.findByRole('region', { name: 'Счета' }, LOADED);
    expect(screen.queryByRole('link', { name: /Написать менеджеру/ })).not.toBeInTheDocument();
    expect(document.querySelector('a[href^="https://t.me"]')).toBeNull();
  });

  it('Mini App: ссылка открывается через Telegram.WebApp.openTelegramLink', async () => {
    const webApp = asMiniApp({ startParam: 'deal_35' });
    const user = userEvent.setup();
    renderApp('/');
    await heading('Сделка № D-35');
    await user.click(await screen.findByRole('link', { name: 'Написать менеджеру' }, LOADED));
    expect(webApp.openTelegramLink).toHaveBeenCalledWith(`${BOT}?start=deal_35`);
  });

  it('веб: клик не перехватывается SDK — работает обычная ссылка', async () => {
    const openTelegramLink = vi.fn();
    // SDK загружен и в браузере, но без initData это не Mini App.
    window.Telegram = { WebApp: { ...asMiniApp(), initData: '', openTelegramLink } };
    signedIn();
    const user = userEvent.setup();
    renderApp('/deals/35');
    await user.click(await screen.findByRole('link', { name: 'Написать менеджеру' }, LOADED));
    expect(openTelegramLink).not.toHaveBeenCalled();
  });
});
