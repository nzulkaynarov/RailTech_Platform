/**
 * Проход через числовую ячейку не должен считаться правкой.
 *
 * Фокус наполняет буфер текущим значением, поэтому уход фокуса записывал его обратно
 * НЕИЗМЕНЁННЫМ: строка помечалась «грязной», загоралось «есть несохранённые изменения», а в
 * стек отмены падал пустой шаг — и первое «Отменить» не давало видимого эффекта, потому что
 * откатывало этот фантом. Найдено прогоном глазами 18-08 (правило на самом деле уже
 * существовало — в ветке очистки нуллируемой ячейки; сюда его не довели).
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { NumericCell } from '../NumericCell';

describe('NumericCell — фантомные правки', () => {
  it('фокус и уход БЕЗ изменений не вызывают onCommit', () => {
    const onCommit = vi.fn();
    render(<NumericCell value="103000" onCommit={onCommit} ariaLabel="цена" />);

    const input = screen.getByLabelText('цена');
    fireEvent.focus(input);
    fireEvent.blur(input);

    expect(onCommit).not.toHaveBeenCalled();
  });

  it('иное написание того же числа — тоже не правка', () => {
    const onCommit = vi.fn();
    render(<NumericCell value="103000.00" onCommit={onCommit} ariaLabel="цена" />);

    const input = screen.getByLabelText('цена');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '103000' } });
    fireEvent.blur(input);

    expect(onCommit).not.toHaveBeenCalled();
  });

  it('настоящая правка по-прежнему доходит', () => {
    const onCommit = vi.fn();
    render(<NumericCell value="103000" onCommit={onCommit} ariaLabel="цена" />);

    const input = screen.getByLabelText('цена');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '345678' } });
    fireEvent.blur(input);

    expect(onCommit).toHaveBeenCalledWith('345678');
  });

  it('правка в пустой ячейке доходит (сравнивать не с чем)', () => {
    const onCommit = vi.fn();
    render(<NumericCell value={null} onCommit={onCommit} ariaLabel="цена" />);

    const input = screen.getByLabelText('цена');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '500' } });
    fireEvent.blur(input);

    expect(onCommit).toHaveBeenCalledWith('500');
  });
});
