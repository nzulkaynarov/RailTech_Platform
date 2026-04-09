/**
 * Domain visual configuration.
 *
 * Maps domain `code` (from DB via API) to icons, colors, and i18n keys.
 * Unknown codes get a sensible fallback — no crash if a new domain is added.
 */
import { Train, Package, Wrench, Box, type LucideIcon } from 'lucide-react';

interface DomainVisual {
  icon: LucideIcon;
  /** Tailwind classes for badge/tab styling */
  badgeClass: string;
  /** Tailwind classes for gradient backgrounds (product detail page) */
  gradientClass: string;
  /** Tailwind classes for large placeholder icon color */
  iconColorClass: string;
  /** Short label for compact tabs (e.g. "RAIL", "GOODS") — i18n key */
  shortLabelKey: string;
  /** Full label — i18n key */
  labelKey: string;
}

/**
 * Known domain visuals keyed by `code`.
 * When a new domain is added in DB, it'll use `FALLBACK` until
 * a designer adds visual config here.
 */
const KNOWN: Record<string, DomainVisual> = {
  RAILWAY_MACHINERY: {
    icon: Train,
    badgeClass: 'bg-primary/10 text-primary border-primary/20',
    gradientClass: 'from-primary/10 to-muted',
    iconColorClass: 'text-primary/30',
    shortLabelKey: 'domains.short.RAILWAY_MACHINERY',
    labelKey: 'domains.RAILWAY_MACHINERY',
  },
  GENERAL_GOODS: {
    icon: Package,
    badgeClass: 'bg-muted text-foreground border-border',
    gradientClass: 'from-muted to-muted',
    iconColorClass: 'text-muted-foreground/30',
    shortLabelKey: 'domains.short.GENERAL_GOODS',
    labelKey: 'domains.GENERAL_GOODS',
  },
  SERVICES: {
    icon: Wrench,
    badgeClass: 'bg-accent text-accent-foreground border-border',
    gradientClass: 'from-accent to-muted',
    iconColorClass: 'text-muted-foreground/30',
    shortLabelKey: 'domains.short.SERVICES',
    labelKey: 'domains.SERVICES',
  },
};

const FALLBACK: DomainVisual = {
  icon: Box,
  badgeClass: 'bg-muted text-foreground border-border',
  gradientClass: 'from-muted to-muted',
  iconColorClass: 'text-muted-foreground/30',
  shortLabelKey: 'domains.unknown',
  labelKey: 'domains.unknown',
};

/**
 * Get visual config for a domain code.
 * Falls back gracefully for unknown codes.
 */
export function getDomainVisual(code: string): DomainVisual {
  return KNOWN[code] ?? FALLBACK;
}

/**
 * Chart-style colors per domain, keyed by code.
 * Uses CSS variable classes for consistency with recharts.
 */
const CHART_COLORS: Record<string, string> = {
  RAILWAY_MACHINERY: 'bg-[var(--color-chart-1)]/10 text-[var(--color-chart-1)]',
  GENERAL_GOODS: 'bg-[var(--color-chart-2)]/10 text-[var(--color-chart-2)]',
  SERVICES: 'bg-[var(--color-chart-3)]/10 text-[var(--color-chart-3)]',
};

const CHART_FALLBACK = 'bg-[var(--color-chart-4)]/10 text-[var(--color-chart-4)]';

export function getDomainChartColor(code: string): string {
  return CHART_COLORS[code] ?? CHART_FALLBACK;
}

/**
 * Build i18n label key for a domain.
 * For known domains, uses the configured key.
 * For unknown domains, falls back to using the DB `name` directly
 * (caller should use `domain.name` from API as fallback).
 */
export function getDomainLabelKey(code: string): string {
  return KNOWN[code]?.labelKey ?? 'domains.unknown';
}

export function getDomainShortLabelKey(code: string): string {
  return KNOWN[code]?.shortLabelKey ?? 'domains.unknown';
}
