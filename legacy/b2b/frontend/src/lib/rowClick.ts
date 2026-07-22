import type React from 'react';

/**
 * Unified «open the document by clicking its row» behaviour for every registry
 * (КП / договоры / инвойсы / акты / платежи / исполнение). A registry is a list of
 * documents; clicking a row opens the document — the pattern every reference product uses
 * (Odoo list→form, PandaDoc list→document). The one subtlety is not stealing clicks that
 * land on a control INSIDE the row (an actions menu, a link, an inline button), which owns
 * its own behaviour. `clickOriginatesFromControl` is that guard, shared by the raw-<Table>
 * pages (via `openableRowProps`) and `ResponsiveDataTable` (via its `onRowClick`).
 */
export function clickOriginatesFromControl(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el?.closest(
    'button, a, input, select, textarea, label, [role="menuitem"], [role="menu"], [data-row-action]',
  );
}

/** Props spread onto a raw `<TableRow>` to make it open its document on click / Enter / Space. */
export function openableRowProps(onOpen: () => void, label: string) {
  return {
    role: 'button' as const,
    tabIndex: 0,
    'aria-label': label,
    className:
      'cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
    onClick: (event: React.MouseEvent) => {
      if (!clickOriginatesFromControl(event.target)) onOpen();
    },
    onKeyDown: (event: React.KeyboardEvent) => {
      // Only the row itself activates on Enter/Space — never a nested focused control.
      if (event.target !== event.currentTarget) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onOpen();
      }
    },
  };
}
