/**
 * «Планшетный провал» навигации.
 *
 * `useIsMobile` считает мобильным только `≤767px`, поэтому на 768–1279px сайдбар оставался
 * развёрнутым на 256px и резал контент ровно на свою ширину: в реестре сделок за экран уходили
 * «Сумма», «Ответственный», «Дата» и колонка действий (проход глазами 03-08, замер
 * `scrollWidth − clientWidth` = 256px). Мобильная ширина была цела — там сайдбар уходит в
 * оверлей; десктоп тоже. Проваливалась ровно середина.
 *
 * Эталон: Odoo, Linear и Notion держат на планшете навигацию СВЁРНУТОЙ В ИКОНКИ.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';

import { TABLET_QUERY, sidebarDefaultOpen } from '../sidebarDefaultOpen';

/** Подменяет matchMedia так, как ответил бы браузер на ширине `width`. */
function stubViewport(width: number) {
  vi.stubGlobal('matchMedia', (query: string) => {
    const min = /min-width:\s*(\d+)px/.exec(query);
    const max = /max-width:\s*(\d+)px/.exec(query);
    const matches = (!min || width >= Number(min[1])) && (!max || width <= Number(max[1]));
    return { matches, media: query, addEventListener() {}, removeEventListener() {} };
  });
}

afterEach(() => vi.unstubAllGlobals());

describe('стартовое состояние сайдбара', () => {
  it.each([
    [375, true, 'мобильная — сайдбар всё равно уходит в оверлей'],
    [767, true, 'граница мобильной'],
    [768, false, 'планшет: начало провала'],
    [1024, false, 'планшет: типичная ширина'],
    [1279, false, 'планшет: конец провала'],
    [1280, true, 'десктоп: места хватает'],
    [1440, true, 'десктоп'],
  ])('%ipx → развёрнут=%s (%s)', (width, expected) => {
    stubViewport(width);

    expect(sidebarDefaultOpen()).toBe(expected);
  });

  it('без matchMedia (тест-среда, SSR) не ломается и остаётся развёрнутым', () => {
    vi.stubGlobal('matchMedia', undefined);

    expect(sidebarDefaultOpen()).toBe(true);
  });

  it('запрос покрывает именно провал между мобильной и десктопной вёрсткой', () => {
    // Дыра была в том, что между «мобильный» (<768) и «широкий десктоп» не было своего режима.
    expect(TABLET_QUERY).toBe('(min-width: 768px) and (max-width: 1279px)');
  });
});
