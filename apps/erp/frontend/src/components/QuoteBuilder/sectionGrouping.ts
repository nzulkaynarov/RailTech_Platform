import type { QuoteItem } from '@/api/crmApi';

/**
 * U5 — group КП lines under their SECTION heading and collapse a section's children.
 *
 * A SECTION heading (display_type === 'SECTION') opens a group; every following non-SECTION row
 * (ITEM / NOTE / legacy undefined) belongs to it until the next SECTION heading or the end of the
 * document. Rows before the first SECTION belong to no group.
 *
 * The collapse-filter is one more layer of the visible-rows pipeline the U4 search feeds:
 *   serverItems → U4 filter → collapse filter → visibleItems
 * so a collapsed section's children leave the list the virtualizer windows and the keyboard
 * navigates — they are genuinely absent, not merely `display:none` (a hidden row still in the list
 * would break the virtualization window and let keyboard nav land on an invisible cell).
 */

const displayTypeOf = (item: Pick<QuoteItem, 'display_type'>): string => item.display_type ?? 'ITEM';

/**
 * Drop the non-SECTION rows that follow a COLLAPSED SECTION (up to the next SECTION). The SECTION
 * heading itself always stays visible — it is the control that re-expands the group. Returns the
 * SAME array reference when nothing is collapsed, so the (common) all-expanded path allocates
 * nothing and downstream identity-keyed memos (virtualizer count, selection prune) do not churn.
 */
export function collapseHiddenItems(items: QuoteItem[], collapsedSectionIds: Set<number>): QuoteItem[] {
	if (collapsedSectionIds.size === 0) return items;
	const result: QuoteItem[] = [];
	let hiding = false;
	for (const item of items) {
		if (displayTypeOf(item) === 'SECTION') {
			hiding = collapsedSectionIds.has(item.id);
			result.push(item);
			continue;
		}
		if (!hiding) result.push(item);
	}
	return result;
}

/**
 * Row ids of the non-SECTION lines that belong to some SECTION (any SECTION earlier in the document,
 * up to the next SECTION). Computed over the FULL document so the left-indent grouping indicator on
 * an ITEM row is stable regardless of the active filter/collapse view.
 */
export function itemsUnderSection(items: QuoteItem[]): Set<number> {
	const under = new Set<number>();
	let inSection = false;
	for (const item of items) {
		if (displayTypeOf(item) === 'SECTION') {
			inSection = true;
			continue;
		}
		if (inSection) under.add(item.id);
	}
	return under;
}
