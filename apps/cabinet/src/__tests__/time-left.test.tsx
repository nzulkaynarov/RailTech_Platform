import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { TimeLeft } from '@/components/TimeLeft';

// Полдень 14.10.2026 в Ташкенте.
const NOW = Date.parse('2026-10-14T07:00:00Z');

describe('TimeLeft (план §3f РЕФ-3)', () => {
  it('считает дни до срока по календарю Ташкента и склоняет', () => {
    expect(render(<TimeLeft date="2026-10-15" now={NOW} />).container).toHaveTextContent('остался 1 день');
    expect(render(<TimeLeft date="2026-10-17" now={NOW} />).container).toHaveTextContent('осталось 3 дня');
    expect(render(<TimeLeft date="2026-10-24" now={NOW} />).container).toHaveTextContent('осталось 10 дней');
    expect(render(<TimeLeft date="2026-10-14" now={NOW} />).container).toHaveTextContent('сегодня последний день');
  });

  it('два дня и меньше — цветом предупреждения; прошедший срок и пустая дата не показываются', () => {
    expect(render(<TimeLeft date="2026-10-16" now={NOW} />).container.firstChild).toHaveClass('text-warning');
    expect(render(<TimeLeft date="2026-10-20" now={NOW} />).container.firstChild).toHaveClass('text-muted-foreground');
    expect(render(<TimeLeft date="2026-10-13" now={NOW} />).container).toBeEmptyDOMElement();
    expect(render(<TimeLeft date={null} now={NOW} />).container).toBeEmptyDOMElement();
  });
});
