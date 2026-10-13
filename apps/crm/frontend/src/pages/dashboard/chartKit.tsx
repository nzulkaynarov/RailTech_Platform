/**
 * Рамка графиков `@ant-design/plots` (грузится лениво вместе с ними): карточка с текстовой
 * альтернативой (role="img" + aria-label) и пустым состоянием.
 */
import { Card } from "antd";
import type { ReactNode } from "react";

import { EmptyState } from "../../components/EmptyState";
import { t } from "../../i18n/ru";

type FrameProps = {
  title: string;
  /** Текстовая альтернатива: заголовок и ключевые числа (domain `summarize`). */
  summary: string;
  empty: boolean;
  children: ReactNode;
  extra?: ReactNode;
  footer?: ReactNode;
};

export function ChartCard({ title, summary, empty, children, extra, footer }: FrameProps) {
  return (
    <Card size="small" title={<h3 className="card-heading">{title}</h3>} extra={extra}>
      {empty ? (
        <EmptyState compact title={t.charts.empty} />
      ) : (
        <div role="img" aria-label={summary} className="chart-frame">
          {children}
        </div>
      )}
      {footer}
    </Card>
  );
}
