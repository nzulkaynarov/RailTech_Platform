import type { LineMirror } from './usePricingMirror';

/** Advisory per-line economics chip data, or null when cost is hidden/unknown. */
export interface LineSignal {
	marginPct: number;
	profit: string;
	belowCost: boolean;
	belowFloor: boolean;
}

/**
 * Per-line economics (advisory chip) narrowed from the live pricing mirror, so a dirty row's
 * margin/loss triage tracks the in-progress edit.
 *
 * Hoisted out of `GridRow` (DT4): it used to be a closure re-allocated on every render of every
 * visible row, and it re-entered `pricingMirror.lineFor()` a second time for the same row. As a
 * plain module-level function it is allocated once and takes the already-resolved `LineMirror`.
 */
export function lineSignalOf(line: LineMirror): LineSignal | null {
	if (line.marginPct == null || line.profit == null) return null;
	return {
		marginPct: line.marginPct,
		profit: line.profit,
		belowCost: line.belowCost,
		belowFloor: line.belowFloor,
	};
}
