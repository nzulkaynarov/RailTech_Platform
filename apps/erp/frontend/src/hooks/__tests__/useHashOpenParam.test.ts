/**
 * Ссылка «открыть документ» должна открывать документ — и с другой страницы, и с этой же.
 *
 * Такие ссылки строят письма, уведомления и глобальный поиск (⌘K). Разбор был у каждой страницы
 * свой: счета делали правильно, договоры читали параметр ТОЛЬКО при монтировании (переход из
 * поиска, когда ты уже на странице договоров, не открывал ничего), а страница актов не читала
 * его вовсе — акт по ссылке не открывался никогда. Найдено прогоном глазами 19-08.
 *
 * Тест держит оба случая и уборку параметра: без неё ручное закрытие карточки или перезагрузка
 * открывали бы её снова.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useHashOpenParam } from '../useHashOpenParam';

beforeEach(() => {
  window.history.replaceState({}, '', '/');
});

describe('useHashOpenParam', () => {
  it('открывает документ при монтировании страницы по ссылке', () => {
    window.history.replaceState({}, '', '/#acts?open=4');
    const onOpen = vi.fn();

    renderHook(() => useHashOpenParam('acts', onOpen));

    expect(onOpen).toHaveBeenCalledWith(4);
  });

  it('открывает документ, когда пользователь УЖЕ на этой странице (смена хеша)', () => {
    window.history.replaceState({}, '', '/#contracts');
    const onOpen = vi.fn();
    renderHook(() => useHashOpenParam('contracts', onOpen));
    expect(onOpen).not.toHaveBeenCalled();

    act(() => {
      window.history.replaceState({}, '', '/#contracts?open=7');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });

    expect(onOpen).toHaveBeenCalledWith(7);
  });

  it('снимает параметр после применения — повторное открытие не навязывается', () => {
    window.history.replaceState({}, '', '/#invoices?open=3');
    renderHook(() => useHashOpenParam('invoices', vi.fn()));

    expect(window.location.hash).toBe('#invoices');
  });

  it('мусор в параметре игнорируется молча', () => {
    window.history.replaceState({}, '', '/#acts?open=abc');
    const onOpen = vi.fn();

    renderHook(() => useHashOpenParam('acts', onOpen));

    expect(onOpen).not.toHaveBeenCalled();
    expect(window.location.hash).toBe('#acts?open=abc');
  });
});
