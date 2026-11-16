import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { CompanyCell, ItemCell, PersonCell } from '@/components/EntityCell';
import { entityInitials } from '@/lib/initials';

describe('entityInitials', () => {
  it('takes the first letters of two words and drops the legal form for a company', () => {
    expect(entityInitials('Каримов Сардор Алиевич')).toBe('КС');
    expect(entityInitials('ООО «Рельс Сервис»', true)).toBe('РС');
    expect(entityInitials('"Temir Yo\'l" MCHJ', true)).toBe('TY');
    expect(entityInitials(' ')).toBe('?');
  });
});

describe('EntityCell', () => {
  it('person: initials without a photo, photo falls back to initials when broken', () => {
    const { container, rerender } = render(<PersonCell name="Каримов Сардор" caption="Снабженец" />);
    expect(container.querySelector('[aria-hidden="true"]')).toHaveTextContent('КС');
    expect(screen.getByText('Снабженец')).toBeInTheDocument();
    rerender(<PersonCell name="Каримов Сардор" photoUrl="/p.jpg" />);
    const img = container.querySelector('img') as HTMLImageElement;
    expect(img).toHaveAttribute('alt', '');
    fireEvent.error(img);
    expect(container.querySelector('img')).toBeNull();
  });

  it('company: letters and INN announced with its label; link only with an address', () => {
    const { container } = render(
      <MemoryRouter>
        <CompanyCell name="ООО «Рельс Сервис»" inn="300000777" to="/company" />
      </MemoryRouter>,
    );
    expect(container).toHaveTextContent('ООО «Рельс Сервис»ИНН: 300000777');
    expect(screen.getByRole('link', { name: 'ООО «Рельс Сервис»' })).toHaveAttribute('href', '/company');
  });

  it('item: type icon without a photo and our article', () => {
    const { container } = render(<ItemCell name="Монтаж стрелки" sku="SV-01" kind="service" />);
    expect(container.querySelector('svg')).not.toBeNull();
    expect(container).toHaveTextContent('Монтаж стрелкиАртикул: SV-01');
  });
});
