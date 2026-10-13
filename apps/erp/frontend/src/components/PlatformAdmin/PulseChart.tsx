import { useMemo } from 'react';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';
import type { AdminPulseDay } from '@/api/adminApi';

export type PulseTone = 'primary' | 'success' | 'info' | 'warning';

const PULSE_TONE_CSS: Record<PulseTone, string> = {
  primary: 'var(--primary)',
  success: 'var(--success)',
  info: 'var(--info)',
  warning: 'var(--warning)',
};

/** Спарклайн-график пульса платформы: площадная диаграмма за выбранный период. */
export function PulseChart({
  series,
  valueKey = 'count',
  tone,
  valueFormatter,
  ariaLabel,
}: {
  series: AdminPulseDay[];
  valueKey?: 'count' | 'value';
  tone: PulseTone;
  valueFormatter?: (v: number) => string;
  ariaLabel?: string;
}) {
  const data = useMemo(
    () =>
      series.map((d) => ({
        date: d.date,
        value: valueKey === 'value' ? Number(d.value) : d.count,
      })),
    [series, valueKey],
  );

  const config: ChartConfig = useMemo(
    () => ({
      value: {
        label: ariaLabel ?? 'Value',
        color: PULSE_TONE_CSS[tone],
      },
    }),
    [tone, ariaLabel],
  );

  if (series.length === 0) {
    return <div className="h-[90px] w-full" aria-hidden="true" />;
  }

  return (
    <ChartContainer config={config} className="h-[90px] w-full">
      <AreaChart
        data={data}
        margin={{ left: 4, right: 4, top: 4, bottom: 0 }}
      >
        <defs>
          <linearGradient id={`pulse-grad-${tone}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={`var(--color-value)`} stopOpacity={0.35} />
            <stop offset="95%" stopColor={`var(--color-value)`} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
        <XAxis
          dataKey="date"
          hide
        />
        <YAxis hide domain={[0, 'dataMax + 1']} />
        <ChartTooltip
          cursor={{ stroke: 'var(--border)', strokeDasharray: '3 3' }}
          content={
            <ChartTooltipContent
              labelFormatter={(value) =>
                new Date(value as string).toLocaleDateString([], {
                  day: '2-digit',
                  month: 'short',
                })
              }
              formatter={(v) => (valueFormatter ? valueFormatter(Number(v)) : String(v))}
              hideIndicator={false}
            />
          }
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke="var(--color-value)"
          strokeWidth={2}
          fill={`url(#pulse-grad-${tone})`}
        />
      </AreaChart>
    </ChartContainer>
  );
}
