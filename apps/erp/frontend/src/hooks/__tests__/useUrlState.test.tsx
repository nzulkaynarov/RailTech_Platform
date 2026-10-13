/**
 * `useUrlState` — ОДИН источник состояния URL на всё приложение.
 *
 * До 19-08 каждый вызов хука держал своё состояние, и перерисовывался только тот экземпляр,
 * который сам записал URL. В админ-реестрах это ломало поиск и вкладки: таблица писала `?q=…`,
 * а страница, собирающая параметры запроса к API, об этом не узнавала — адресная строка и
 * подсветка менялись, список нет, запрос не уходил. Оператор делал вывод «записи нет».
 *
 * ВАЖНО ПРО САМ ТЕСТ: проверять надо ПЕРЕРИСОВКУ соседа, а не значение `get()`. Первая версия
 * этого файла звала `get()` императивно после записи — и проходила даже на сломанной
 * реализации, потому что `get()` читал `window.location` напрямую. Ломается же именно то, что
 * компонент не узнаёт о смене URL и продолжает показывать (и запрашивать) старое.
 */

import { useEffect } from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';

import { useUrlState } from '../useUrlState';

type UrlSetter = ReturnType<typeof useUrlState>['set'];
/** Ручка на `set` соседнего экземпляра. Кладём её В ЭФФЕКТЕ: запись в рендере — нечистый
 *  рендер, и правило `react-hooks/globals` совершенно справедливо на неё ругается. */
const api: { set?: UrlSetter } = {};
const writerSet: UrlSetter = (entries) => api.set?.(entries);

/** Сосед: показывает то, что вычислил ВО ВРЕМЯ РЕНДЕРА, и считает свои рендеры. */
function Reader({ renders }: { renders: { count: number } }) {
  const { get } = useUrlState();
  renders.count += 1;
  return <div data-testid="reader">{get('adminUsers.q') || '—'}</div>;
}

function Writer() {
  const { set } = useUrlState();
  useEffect(() => {
    api.set = set;
  }, [set]);
  return null;
}

beforeEach(() => {
  window.history.replaceState({}, '', '/');
});

describe('useUrlState', () => {
  it('запись в ОДНОМ экземпляре перерисовывает ДРУГОЙ (это и ломало поиск в реестрах)', () => {
    const renders = { count: 0 };
    render(
      <>
        <Writer />
        <Reader renders={renders} />
      </>,
    );
    expect(screen.getByTestId('reader').textContent).toBe('—');
    const before = renders.count;

    act(() => writerSet({ 'adminUsers.q': 'kamol' }));

    expect(renders.count).toBeGreaterThan(before); // сосед узнал о смене URL
    expect(screen.getByTestId('reader').textContent).toBe('kamol');
  });

  it('очистка ключа тоже доходит до соседа', () => {
    const renders = { count: 0 };
    render(
      <>
        <Writer />
        <Reader renders={renders} />
      </>,
    );
    act(() => writerSet({ 'adminUsers.q': 'ось' }));
    expect(screen.getByTestId('reader').textContent).toBe('ось');

    act(() => writerSet({ 'adminUsers.q': '' }));

    expect(screen.getByTestId('reader').textContent).toBe('—');
    expect(window.location.search).not.toContain('adminUsers.q');
  });

  it('повторная запись того же значения не трогает ни историю, ни соседа', () => {
    const renders = { count: 0 };
    render(
      <>
        <Writer />
        <Reader renders={renders} />
      </>,
    );
    act(() => writerSet({ 'adminUsers.q': 'ось' }));
    const search = window.location.search;
    const renderCount = renders.count;

    act(() => writerSet({ 'adminUsers.q': 'ось' }));

    expect(window.location.search).toBe(search);
    expect(renders.count).toBe(renderCount);
  });

  it('несколько ключей пишутся одной записью', () => {
    const renders = { count: 0 };
    render(
      <>
        <Writer />
        <Reader renders={renders} />
      </>,
    );

    act(() => writerSet({ 'adminUsers.q': 'рельс', tab: 'drafts', page: '2' }));

    expect(screen.getByTestId('reader').textContent).toBe('рельс');
    expect(window.location.search).toContain('tab=drafts');
    expect(window.location.search).toContain('page=2');
  });
});
